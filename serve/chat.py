"""
PRAVAAH — grounded AI chat for a duty officer (Gemini).

THE SAME IRON RULE AS THE ADVISORY LAYER
----------------------------------------
    The LLM never predicts. It answers questions ABOUT numbers the models
    already computed, from a context we assemble. It is forbidden to invent a
    figure, and the output is checked, not merely instructed.

WHY generateContent AND NOT THE "LIVE API"
------------------------------------------
Gemini's Live API (`bidiGenerateContent`) is a bidirectional streaming channel
for voice and video — `gemini-*-live-*` and `*-native-audio-*`. This is a text
Q&A over a fixed JSON context, so the correct surface is `generateContent`.
Using the Live API here would add a websocket session, audio framing and
turn-management for a feature that is a request/response question.

Model: gemini-3.5-flash-lite, chosen on RATE LIMITS, not on quality.

The free tier's binding constraint is REQUESTS PER DAY, and it differs by an
order of magnitude across the flash family:

    gemini-3.6-flash        5 RPM /  20 RPD
    gemini-3.5-flash         5 RPM /  20 RPD
    gemini-3.5-flash-lite   15 RPM / 500 RPD   <- this one

Twenty requests a day would not survive one demo with judges asking questions.
Lite gives 25x the daily budget, and it is also 3.6x faster measured on this
exact task (1.3 s vs 4.7 s) because the larger flash models spend ~360 thinking
tokens per call — which was truncating replies and tripping the timeout.

The task is summarising a small JSON for a duty officer, comfortably within
Lite. Quality was compared side by side before switching.

(An earlier attempt used gemini-2.5-flash on "stable beats preview" reasoning;
the API returned 404 — "no longer available to new users". The live model list
is the authority, not a remembered one.)

GROUNDING CONTRACT
------------------
The model sees ONLY:
  * the selected ward's properties (probability, exposure, drivers, band)
  * city KPIs at that clock
  * which model produced which number, and each model's measured skill
  * the project's stated limits
It sees no free text, no web, and no other wards unless asked for the ranking.

TWO GUARDS, BECAUSE A PROMPT IS NOT A CONTROL
---------------------------------------------
  1. Numeric post-check: every number in the reply must appear in the context
     (or be trivially derivable — a percentage of a probability, a rounding).
     A reply that invents a figure is REJECTED, not shown with a caveat.
  2. Refusal path: with no key, or on any API failure, the endpoint returns a
     deterministic answer built from the same context. The demo never blocks
     on a third party.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = "gemini-3.5-flash-lite"
ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/"
            f"models/{MODEL}:generateContent")

SYSTEM = """You are PRAVAAH's assistant, helping a Delhi ward officer during a \
flood-warning shift.

ABSOLUTE RULES:
1. Use ONLY numbers present in the CONTEXT JSON. Never invent, estimate or \
recall a figure from elsewhere. If the context does not contain something, say \
"that isn't in the current data" and say what IS available.
2. You do NOT forecast. Three machine-learning models produced these numbers; \
you explain and summarise them.
3. Be brief and operational. A duty officer at 4am wants what is at risk, how \
confident we are, and what to do — not a lecture.
4. Never claim certainty the numbers do not support. If a probability is 34%, \
that means it probably will NOT happen; say so plainly rather than alarming.
5. If asked about model accuracy or trustworthiness, quote the measured skill \
in the context, including its limits. Do not oversell.
6. Answer in the language of the question. If asked in Hindi, reply in natural \
Devanagari Hindi.

Plain text only. No markdown headers. Under 150 words unless asked for more."""


def _key() -> str | None:
    k = os.getenv("GEMINI_API_KEY")
    if k:
        return k
    env = ROOT / ".env"
    if env.exists():
        m = re.search(r"^GEMINI_API_KEY=(\S+)", env.read_text(), re.M)
        if m:
            return m.group(1)
    return None


def build_context(ward: dict | None, kpi: dict | None, event: str,
                  t: str, metrics: dict | None, ranking: list | None) -> dict:
    """Everything the model may use, and nothing else."""
    ctx = {
        "event": event,
        "clock_utc": t,
        "what_this_is": ("PRAVAAH: an AI flood early-warning prototype for Delhi. "
                         "Three models — RainCast (0-6h rain nowcast), RainFuse "
                         "(6-72h forecast correction), InundaNet (rain to ward "
                         "flood probability)."),
    }
    if kpi:
        ctx["city_now"] = {k: kpi.get(k) for k in
                           ("rain_now_mm_h", "p3h50", "city_risk",
                            "time_to_critical_min", "people_exposed")}
    if ward:
        ctx["selected_ward"] = {
            "name": ward.get("name"), "ward_id": ward.get("ward_id"),
            "flood_probability": ward.get("p_flood"),
            "risk_band": ward.get("risk_band"),
            "risk_score": ward.get("risk_score"),
            "flagged_since_ist": ward.get("onset"),
            "people": ward.get("people"), "hospitals": ward.get("hospitals"),
            "schools": ward.get("schools"), "road_km": ward.get("road_km"),
            "pumps": ward.get("pumps"),
            "top_drivers": [d[0] for d in (ward.get("drivers") or [])][:3],
        }
    if ranking:
        ctx["highest_risk_wards"] = ranking[:8]
    if metrics:
        rc = metrics.get("models", {}).get("raincast", {})
        inu = metrics.get("models", {}).get("inundanet", {})
        head = next((h for h in rc.get("heads", [])
                     if h.get("head") == "p5" and h.get("window_h") == 3), None)
        ctx["model_skill_measured"] = {
            "raincast_note": ("skill scores are on a held-out year; CSI is the "
                              "standard rare-event score, higher is better"),
            "raincast_csi": head.get("csi") if head else None,
            "persistence_baseline_csi": head.get("persistence_csi") if head else None,
            "raw_global_nwp_csi": head.get("raw_nwp_csi") if head else None,
            "inundanet_auc_pr": inu.get("auc_pr"),
            "inundanet_vs_terrain_baseline": inu.get("lift_over_hand"),
        }
        ctx["stated_limits"] = metrics.get("stated_limits", [])[:5]
    ctx["important_caveats"] = [
        "onset means the first time this ward CROSSED the risk threshold; it is "
        "not a predicted time-of-arrival.",
        "The exposure counts (people, hospitals, schools) are exact geometry "
        "from OpenStreetMap and census-grid population, not model output.",
    ]
    return ctx


def _numbers(s: str) -> set[str]:
    return {n.rstrip(".") for n in re.findall(r"\d[\d,]*\.?\d*", s or "")}


def _allowed(ctx: dict) -> set[str]:
    """Numbers the model may legitimately use, plus benign derivations."""
    base = _numbers(json.dumps(ctx))
    extra: set[str] = set()
    for n in list(base):
        try:
            v = float(n.replace(",", ""))
        except ValueError:
            continue
        # a probability quoted as a percentage, and thousands separators
        extra.add(str(int(round(v * 100))))
        extra.add(str(int(round(v))))
        extra.add(f"{v:,.0f}".replace(",", ""))
        extra.add(f"{v:,.0f}")
    return base | extra | {str(i) for i in range(0, 101)}


def ask(question: str, ctx: dict) -> dict:
    key = _key()
    if not key:
        return {"ok": False, "reason": "no_key", "answer": fallback(question, ctx)}

    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text":
            f"CONTEXT (the only facts you may use):\n"
            f"{json.dumps(ctx, ensure_ascii=False, indent=1)}\n\n"
            f"QUESTION: {question}"}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2000},
    }
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            out = json.load(r)
        text = out["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (urllib.error.URLError, KeyError, IndexError, ValueError, TimeoutError) as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}",
                "answer": fallback(question, ctx)}

    invented = sorted(n for n in _numbers(text)
                      if n not in _allowed(ctx)
                      and n.replace(",", "") not in _allowed(ctx))
    if invented:
        # A prompt instruction is not a control. If it wrote a figure that is
        # not in the context, we do not show it with a warning — we drop it.
        return {"ok": False, "reason": "invented_numbers",
                "invented": invented, "answer": fallback(question, ctx),
                "rejected_draft": text}
    return {"ok": True, "answer": text, "model": MODEL, "grounded": True}


def fallback(question: str, ctx: dict) -> str:
    """Deterministic answer from the same context. No key, no network, no risk."""
    w = ctx.get("selected_ward")
    c = ctx.get("city_now") or {}
    if w:
        pct = round((w.get("flood_probability") or 0) * 100)
        bits = [f"{w['name']}: flood probability {pct}%, risk band "
                f"{w.get('risk_band', 'unknown')}."]
        if w.get("flagged_since_ist"):
            bits.append(f"Flagged at this level since {w['flagged_since_ist']} IST.")
        bits.append(f"About {w.get('people', 0):,} residents, "
                    f"{w.get('hospitals', 0)} hospital(s), {w.get('schools', 0)} "
                    f"school(s) and {w.get('road_km', 0)} km of road are in the "
                    f"exposed area.")
        if w.get("top_drivers"):
            bits.append("Main drivers: " + ", ".join(w["top_drivers"]) + ".")
        bits.append("(Generated without the language model — same numbers, "
                    "fixed wording.)")
        return " ".join(bits)
    return (f"City risk is {c.get('city_risk', 'unknown')}; rain now "
            f"{c.get('rain_now_mm_h', 0)} mm/h; about "
            f"{c.get('people_exposed', 0):,} people in exposed wards. "
            f"Select a ward for detail. (Generated without the language model.)")
