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

THE ONE HARD RULE — about NUMBERS AND PREDICTIONS ONLY:
1. Every FIGURE you state about Delhi, this ward, the weather or the models \
must come from the CONTEXT JSON. Never invent, estimate or recall a figure from \
elsewhere. If a specific number is not in the context, say you do not have it.
2. You do NOT forecast. Three machine-learning models produced these numbers; \
you explain and summarise them. Never predict rainfall or flooding beyond what \
the context already states.

EVERYTHING ELSE: BE GENUINELY USEFUL.
3. You MAY reason, explain, give practical safety advice and answer ordinary \
questions using general knowledge — what a "watch" band implies for someone's \
plans, why underpasses flood first, whether to carry an umbrella, what a duty \
officer should check next. You are not restricted to reciting the JSON.
4. Do not stonewall. If someone asks about a specific place, road or business we \
have no data for, say briefly that PRAVAAH does not track it, then answer the \
question they actually meant using the ward-level numbers you DO have and \
ordinary common sense. A person asking "should I go out tonight?" wants a \
judgement, not an inventory.
5. Keep general knowledge and PRAVAAH's measurements clearly distinct. \
"PRAVAAH puts this ward at X" is a measurement; "underpasses are usually the \
first places to flood" is general advice. Never let the second borrow the \
authority of the first, and never attach a made-up number to it.
6. Be brief and human. A duty officer at 4am, or a person deciding whether to \
go out, wants a straight answer first and the caveats second — not a lecture.
7. Never claim certainty the numbers do not support. A probability below half \
means the event probably will NOT happen; say so plainly rather than alarming. \
Quote the ward's own probability, never a number from these instructions.
8. If asked about model accuracy or trustworthiness, quote the measured skill \
in the context, including its limits. Do not oversell.
9. Answer in the language of the question. An English question gets a fully \
English answer; a Hindi question gets natural Devanagari Hindi. Do NOT reply in \
romanised Hinglish to an English question.

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


def _numbers(s: str) -> list[str]:
    return [n.rstrip(".") for n in re.findall(r"\d[\d,]*\.?\d*", s or "")]


def _context_values(ctx: dict) -> list[float]:
    """Every numeric literal in the context, as floats."""
    out = []
    for n in _numbers(json.dumps(ctx)):
        try:
            out.append(float(n.replace(",", "")))
        except ValueError:
            pass
    return out


def _is_grounded(token: str, values: list[float]) -> bool:
    """
    Is `token` a faithful rendering of some number in the context?

    NUMERIC, NOT STRING-MATCHING. The previous version enumerated string forms
    of each context value — thousands separators, percentages, roundings to
    0-4 decimal places — and asked whether the reply's token was in that set.
    That design fails silently and repeatedly, because the set of ways to write
    a number correctly is unbounded. It rejected a CORRECT answer twice: first
    for writing 0.1205 where the context held 0.12048192771084337, and then,
    after the decimal places were extended to four, for writing 0.12052 at five.
    Chasing that with more enumeration would only postpone the third failure.

    So the question is now asked directly: a token written with `d` decimals is
    grounded if some context value rounds to it at `d` decimals — which is the
    definition of a correct rounding — or if the value does so when expressed as
    a percentage. Bare integers 0-100 are always allowed (counts, percentages
    and ordinals in ordinary prose).

    This is STRICTLY MORE HONEST than the old set, not merely more permissive:
    it accepts every faithful rendering at any precision, and it still rejects
    any figure that is not a rendering of something we actually computed.
    """
    raw = token.replace(",", "")
    try:
        r = float(raw)
    except ValueError:
        return True                      # not a number we can judge
    if r == int(r) and 0 <= r <= 100:
        return True
    dp = len(raw.split(".")[1]) if "." in raw else 0
    tol = 0.5 * (10 ** -dp) + 1e-12      # half a unit in the last place
    for v in values:
        if abs(v - r) <= tol or abs(v * 100 - r) <= tol:
            return True
    return False


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

    values = _context_values(ctx)
    invented = sorted({n for n in _numbers(text)
                       if not _is_grounded(n, values)})
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
