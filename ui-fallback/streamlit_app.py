"""
PRAVAAH — Streamlit validation harness / emergency fallback demo.

Reads data/outputs/ DIRECTLY from disk (no FastAPI in the loop), so it stays a
true independent fallback. File shapes are the frozen contracts in
serve/schemas.py (PRAVAAH.md 12.2). Numbers may be fake placeholders now and
real model output later — this code does not care.

Run:
    conda run -n pravaah --no-capture-output \
        streamlit run ui-fallback/streamlit_app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
REPO = Path(__file__).resolve().parents[1]
OUTPUTS = REPO / "data" / "outputs"
# metrics.json has been seen in two places; try both, first hit wins.
METRICS_CANDIDATES = [
    REPO / "reports" / "metrics.json",
    OUTPUTS / "reports" / "metrics.json",
]

IMD_CATEGORIES = {
    "64.5": "Heavy (64.5-115.5)",
    "115.6": "Very heavy (115.6-204.4)",
    "204.5": "Extremely heavy (>=204.5)",
}

BAND_COLOR = {
    "low": "#2e9e5b",
    "watch": "#f2c14e",
    "high": "#ef7b34",
    "critical": "#c0392b",
}
BADGE_ICON = {"ok": "OK", "degraded": "DEGRADED", "down": "DOWN"}

st.set_page_config(
    page_title="PRAVAAH — validation harness",
    page_icon="🌧️",
    layout="wide",
)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def dash(value, fmt: str = "{}") -> str:
    """None-safe display. Never print the word 'None' at a judge."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, (list, tuple)):
        if not value:
            return "—"
        return " – ".join(dash(v) for v in value)
    try:
        return fmt.format(value)
    except (ValueError, TypeError):
        return str(value)


def _stamp(path: Path) -> float:
    """mtime used as a cache key so regenerated files are picked up."""
    try:
        return path.stat().st_mtime
    except OSError:
        return -1.0


@st.cache_data(show_spinner=False)
def _read_json(path_str: str, mtime: float):
    with open(path_str, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_json(path: Path, label: str, quiet: bool = False):
    """Read a JSON file, or warn (never traceback) and return None."""
    if not path.exists():
        if not quiet:
            st.warning(f"Missing {label}: `{path.relative_to(REPO)}` not found.")
        return None
    try:
        return _read_json(str(path), _stamp(path))
    except Exception as exc:  # noqa: BLE001 - demo night: never crash
        if not quiet:
            st.warning(f"Could not read {label} (`{path.name}`): {exc}")
        return None


def color_for(value: float) -> str:
    """Continuous green -> yellow -> orange -> red ramp for 0..1 values."""
    try:
        v = max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return "#9e9e9e"
    stops = [
        (0.00, (46, 158, 91)),
        (0.35, (242, 193, 78)),
        (0.65, (239, 123, 52)),
        (1.00, (192, 57, 43)),
    ]
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if v <= p1:
            t = 0.0 if p1 == p0 else (v - p0) / (p1 - p0)
            rgb = [int(round(a + (b - a) * t)) for a, b in zip(c0, c1)]
            return "#%02x%02x%02x" % tuple(rgb)
    return "#c0392b"


# --------------------------------------------------------------------------
# Data access — every reader is cached and every reader is None-tolerant
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_index(mtime: float):
    path = OUTPUTS / "index.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def wards_path(event: str, ts: str) -> Path:
    return OUTPUTS / event / f"wards_{ts}.geojson"


def load_wards(event: str, ts: str):
    return load_json(wards_path(event, ts), f"ward layer {ts}")


def load_rain(event: str, ts: str):
    return load_json(OUTPUTS / event / f"rain_grid_{ts}.json", f"rain grid {ts}")


def load_kpi(event: str, ts: str):
    return load_json(OUTPUTS / event / f"kpi_{ts}.json", f"KPIs {ts}")


def load_advisory(event: str, ward_id: str, ts: str):
    return load_json(
        OUTPUTS / event / f"advisory_{ward_id}_{ts}.json", "advisory", quiet=True
    )


def load_metrics():
    for path in METRICS_CANDIDATES:
        if path.exists():
            return load_json(path, "metrics.json"), path
    return None, None


@st.cache_data(show_spinner=False)
def ward_table(event: str, ts: str, mtime: float) -> pd.DataFrame:
    """Ward properties (geometry dropped) for one timestamp."""
    gj = load_json(wards_path(event, ts), f"ward layer {ts}", quiet=True)
    if not gj or "features" not in gj:
        return pd.DataFrame()
    rows = [f.get("properties", {}) for f in gj["features"]]
    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamp"] = ts
    return df


@st.cache_data(show_spinner=False)
def ward_history(event: str, timestamps: tuple[str, ...], stamps: tuple[float, ...]) -> pd.DataFrame:
    """All ward properties across all timestamps — powers the timeline."""
    frames = []
    for ts in timestamps:
        df = ward_table(event, ts, _stamp(wards_path(event, ts)))
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
st.sidebar.title("PRAVAAH")
st.sidebar.caption("Validation harness · reads `data/outputs/` directly")

index = load_index(_stamp(OUTPUTS / "index.json"))

if not index or not index.get("events"):
    st.title("PRAVAAH — validation harness")
    st.warning(
        f"No events found. Expected `{OUTPUTS}/index.json` with an `events` list.\n\n"
        "Run the fake-data generator (`scripts/make_fakes.py`) or the precompute "
        "step, then reload this page."
    )
    st.stop()

events = index["events"]
event_labels = {e["id"]: f'{e.get("name", e["id"])} ({e["id"]})' for e in events}
event_id = st.sidebar.selectbox(
    "Event",
    [e["id"] for e in events],
    format_func=lambda i: event_labels.get(i, i),
)
event = next(e for e in events if e["id"] == event_id)
timestamps = list(event.get("timestamps") or [])

if not timestamps:
    st.warning(f"Event `{event_id}` declares no timestamps in index.json.")
    st.stop()

if len(timestamps) > 1:
    ts = st.sidebar.select_slider("Timestamp (UTC)", options=timestamps, value=timestamps[0])
else:
    ts = timestamps[0]
    st.sidebar.info(f"Only one timestamp: {ts}")

ts_idx = timestamps.index(ts)

st.sidebar.markdown("### Layers")
ward_layer = st.sidebar.radio(
    "Ward colouring", ["p_flood", "risk_score"], horizontal=True
)
rain_layer = st.sidebar.selectbox(
    "Rain field", ["p15", "p50", "q10", "q50", "q90"], index=0
)
show_map = st.sidebar.checkbox("Render ward map", value=True,
                               help="Uncheck if the map is slow while scrubbing.")

st.sidebar.markdown("---")
st.sidebar.caption(
    f"schema v{index.get('schema', '?')} · {event.get('wards', '?')} wards · "
    f"frame {ts_idx + 1}/{len(timestamps)}"
)
st.sidebar.caption(f"Root: `{OUTPUTS}`")

# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
st.title("PRAVAAH — heavy-rainfall & urban inundation early warning")
st.caption(
    f"**{event.get('name', event_id)}** · frame **{ts}** UTC "
    f"({ts_idx + 1} of {len(timestamps)})"
)

tab_cmd, tab_rain, tab_ward, tab_verify = st.tabs(
    ["Command", "Rain", "Ward detail", "Verification"]
)

wards_gj = load_wards(event_id, ts)
wdf = ward_table(event_id, ts, _stamp(wards_path(event_id, ts)))


# ==========================================================================
# TAB 1 — COMMAND
# ==========================================================================
with tab_cmd:
    kpi = load_kpi(event_id, ts)

    if kpi:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Rain now", dash(kpi.get("rain_now_mm_h"), "{:.1f} mm/h"))
        c2.metric("P(>50 mm / 3 h)", dash(kpi.get("p3h50"), "{:.0%}"))
        c3.metric("City risk", dash(kpi.get("city_risk")))
        c4.metric("Time to critical", dash(kpi.get("time_to_critical_min"), "{} min"))
        c5.metric("People exposed", dash(kpi.get("people_exposed"), "{:,}"))

        badges = kpi.get("badges") or {}
        if badges:
            cols = st.columns(len(badges))
            for col, (feed, state) in zip(cols, badges.items()):
                col.markdown(
                    f"**{feed.upper()}** · `{BADGE_ICON.get(state, dash(state))}`"
                )
    else:
        st.info("No KPI file for this frame — map and ranking below still work.")

    st.markdown("---")

    if wdf.empty:
        st.warning(f"No ward data for frame {ts}.")
    else:
        left, right = st.columns([3, 2])

        with left:
            st.subheader("Ward risk map")
            if not show_map:
                st.info("Map rendering is off (sidebar).")
            elif not wards_gj:
                st.warning("Ward GeoJSON unavailable — see the ranking table.")
            else:
                try:
                    import folium
                    from streamlit_folium import st_folium

                    # decorate properties for the tooltip (None -> em dash)
                    feats = []
                    for f in wards_gj.get("features", []):
                        p = dict(f.get("properties", {}))
                        p["_p"] = f'{dash(p.get("p_flood"), "{:.0%}")}'
                        p["_onset"] = dash(p.get("onset"))
                        p["_peak"] = dash(p.get("peak"))
                        p["_band"] = dash(p.get("risk_band"))
                        p["_score"] = dash(p.get("risk_score"), "{:.2f}")
                        p["_name"] = dash(p.get("name"))
                        feats.append({**f, "properties": p})
                    decorated = {"type": "FeatureCollection", "features": feats}

                    # OFFLINE RULE (PRAVAAH.md §11.1, charter R1): tiles=None.
                    # This harness is the EMERGENCY DEMO — it must pass the same
                    # airplane-mode gate as React. Any external basemap (OSM,
                    # CartoDB) is a network dependency and renders as grey
                    # squares with wifi off. Our own ward GeoJSON on a dark
                    # canvas needs no tile server and looks like a control room.
                    fmap = folium.Map(
                        location=[28.61, 77.21],
                        zoom_start=10,
                        tiles=None,
                    )

                    def _style(feature, _field=ward_layer):
                        val = feature["properties"].get(_field)
                        return {
                            "fillColor": color_for(val),
                            "color": "#555555",
                            "weight": 0.4,
                            "fillOpacity": 0.72,
                        }

                    gjson = folium.GeoJson(
                        decorated,
                        style_function=_style,
                        highlight_function=lambda _f: {"weight": 2, "color": "#000000"},
                        tooltip=folium.GeoJsonTooltip(
                            fields=["_name", "_p", "_onset", "_peak", "_band", "_score"],
                            aliases=[
                                "Ward", "P(flood)", "Onset", "Peak",
                                "Band", "Risk score",
                            ],
                            sticky=True,
                        ),
                    )
                    gjson.add_to(fmap)
                    # NOTE: do not use fit_bounds() here. Inside the component
                    # iframe Leaflet measures a zero-size container and lands on
                    # a world-view zoom. Centre explicitly instead.
                    try:
                        (s, w), (n, e) = gjson.get_bounds()
                        fmap.location = [(s + n) / 2.0, (w + e) / 2.0]
                        span = max(n - s, e - w)
                        fmap.options["zoom"] = (
                            12 if span < 0.15 else 11 if span < 0.35 else 10
                        )
                    except Exception:  # noqa: BLE001
                        pass

                    st_folium(
                        fmap,
                        height=520,
                        use_container_width=True,  # streamlit-folium's own kwarg
                        returned_objects=[],
                        key=f"map_{event_id}_{ts}_{ward_layer}",
                    )
                    st.caption(
                        f"Coloured by **{ward_layer}** — green (low) to red (critical)."
                    )
                except Exception as exc:  # noqa: BLE001
                    st.warning(f"Map could not be rendered ({exc}). Table still below.")

        with right:
            st.subheader("Risk band mix")
            if "risk_band" in wdf:
                counts = wdf["risk_band"].value_counts()
                order = ["critical", "high", "watch", "low"]
                for band in order:
                    if band in counts:
                        st.markdown(
                            f'<span style="color:{BAND_COLOR[band]};font-weight:700">'
                            f"■ {band.upper()}</span> &nbsp; {int(counts[band])} wards",
                            unsafe_allow_html=True,
                        )
            for col, label, fmt in [
                ("people", "People in wards ≥ high", "{:,}"),
                ("hospitals", "Hospitals ≥ high", "{:,}"),
                ("schools", "Schools ≥ high", "{:,}"),
            ]:
                if col in wdf and "risk_band" in wdf:
                    sub = wdf[wdf["risk_band"].isin(["high", "critical"])]
                    st.metric(label, fmt.format(int(sub[col].fillna(0).sum())))

        st.subheader("Wards ranked by risk")
        cols = [
            c
            for c in [
                "ward_id", "name", "risk_score", "risk_band", "p_flood",
                "onset", "peak", "people", "hospitals", "schools",
                "road_km", "pumps",
            ]
            if c in wdf.columns
        ]
        table = wdf[cols].copy()
        if "risk_score" in table:
            table = table.sort_values("risk_score", ascending=False)
        for c in ("onset", "peak"):
            if c in table:
                table[c] = table[c].map(lambda v: dash(v))
        st.dataframe(
            table.reset_index(drop=True),
            width="stretch",
            height=420,
            column_config={
                "p_flood": st.column_config.ProgressColumn(
                    "p_flood", min_value=0.0, max_value=1.0, format="%.2f"
                ),
                "risk_score": st.column_config.ProgressColumn(
                    "risk_score", min_value=0.0, max_value=1.0, format="%.2f"
                ),
            },
        )


# ==========================================================================
# TAB 2 — RAIN
# ==========================================================================
with tab_rain:
    rain = load_rain(event_id, ts)
    if not rain:
        st.warning(f"No rain grid for frame {ts}.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Kind", dash(rain.get("kind")).upper())
        c2.metric("Nowcast lead", dash(rain.get("lead_h"), "{} h"))
        cells = rain.get("cells") or []
        c3.metric("Grid points", dash(len(cells), "{:,}"))

        if not cells:
            st.warning("Rain grid contains no cells.")
        else:
            cdf = pd.DataFrame(cells)
            field = rain_layer if rain_layer in cdf.columns else "p15"
            if field != rain_layer:
                st.info(f"Field `{rain_layer}` not present — showing `{field}`.")

            left, right = st.columns([3, 2])
            with left:
                st.subheader(f"Rain lattice — {field}")
                try:
                    import matplotlib.pyplot as plt

                    fig, ax = plt.subplots(figsize=(6, 5))
                    is_prob = field.startswith("p")
                    sc = ax.scatter(
                        cdf["lon"], cdf["lat"],
                        c=cdf[field],
                        s=320, marker="s",
                        cmap="YlGnBu" if not is_prob else "RdYlBu_r",
                        vmin=0.0,
                        vmax=1.0 if is_prob else max(float(cdf[field].max()), 1e-6),
                        edgecolors="#ffffff", linewidths=0.5,
                    )
                    fig.colorbar(
                        sc, ax=ax,
                        label=f"{field}" + (" (probability)" if is_prob else " (mm)"),
                    )
                    ax.set_xlabel("longitude")
                    ax.set_ylabel("latitude")
                    ax.set_title(f"{dash(rain.get('kind')).upper()} · frame {ts} UTC")
                    ax.set_aspect("equal", adjustable="datalim")
                    fig.tight_layout()
                    st.pyplot(fig, width="stretch")
                    plt.close(fig)
                except Exception as exc:  # noqa: BLE001
                    st.warning(f"Could not draw the lattice ({exc}).")
                    st.dataframe(cdf, width="stretch")

            with right:
                st.subheader("Forecast thresholds (IMD)")
                fc = rain.get("forecast")
                if not fc:
                    st.info("No `forecast` block in this rain grid file.")
                else:
                    st.caption(f"Forecast lead: **{dash(fc.get('lead_h'), '{} h')}**")
                    thresholds = fc.get("thresholds") or {}
                    rows = []
                    for key in ("64.5", "115.6", "204.5"):
                        if key in thresholds:
                            rows.append(
                                {
                                    "IMD category (mm/day)": IMD_CATEGORIES[key],
                                    "P(exceed)": thresholds[key],
                                }
                            )
                    for key, val in thresholds.items():
                        if key not in IMD_CATEGORIES:
                            rows.append(
                                {
                                    "IMD category (mm/day)": f">= {key}",
                                    "P(exceed)": val,
                                }
                            )
                    if rows:
                        st.dataframe(
                            pd.DataFrame(rows),
                            width="stretch",
                            hide_index=True,
                            column_config={
                                "IMD category (mm/day)": st.column_config.TextColumn(
                                    "IMD category (mm/day)", width="medium"
                                ),
                                "P(exceed)": st.column_config.ProgressColumn(
                                    "P(exceed)", min_value=0.0, max_value=1.0,
                                    format="%.2f",
                                ),
                            },
                        )
                    else:
                        st.info("Forecast block carries no thresholds.")

                st.subheader("Cell statistics")
                stat_cols = [c for c in ["p15", "p50", "q10", "q50", "q90"]
                             if c in cdf.columns]
                if stat_cols:
                    st.dataframe(
                        cdf[stat_cols].describe().T[["mean", "min", "50%", "max"]],
                        width="stretch",
                    )

            with st.expander("Raw lattice values"):
                st.dataframe(cdf, width="stretch", height=320)


# ==========================================================================
# TAB 3 — WARD DETAIL
# ==========================================================================
with tab_ward:
    if wdf.empty:
        st.warning(f"No ward data for frame {ts}.")
    else:
        ranked = wdf.sort_values("risk_score", ascending=False) \
            if "risk_score" in wdf else wdf
        ids = ranked["ward_id"].tolist()
        names = dict(zip(ranked["ward_id"], ranked.get("name", ranked["ward_id"])))

        ward_id = st.selectbox(
            "Ward (ranked by risk at this frame)",
            ids,
            format_func=lambda w: f"{names.get(w, w)} — {w}",
        )
        row = wdf[wdf["ward_id"] == ward_id].iloc[0].to_dict()

        st.subheader(f'{dash(row.get("name"))} · `{ward_id}`')
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("P(flood)", dash(row.get("p_flood"), "{:.0%}"))
        m2.metric("Risk score", dash(row.get("risk_score"), "{:.2f}"))
        m3.metric("Band", dash(row.get("risk_band")).upper())
        m4.metric("Onset (IST)", dash(row.get("onset")))
        st.caption(
            f"Peak: **{dash(row.get('peak'))}** · "
            f"90% interval: **{dash(row.get('ci90'))}**"
        )

        left, right = st.columns(2)

        with left:
            st.subheader("P(flood) timeline")
            hist = ward_history(
                    event_id,
                    tuple(timestamps),
                    tuple(_stamp(wards_path(event_id, t)) for t in timestamps),
                )
            if hist.empty or "ward_id" not in hist:
                st.warning("No history available across timestamps.")
            else:
                upto = timestamps[: ts_idx + 1]
                series = hist[
                    (hist["ward_id"] == ward_id) & (hist["timestamp"].isin(upto))
                ].copy()
                if series.empty:
                    st.warning("This ward has no history in the loaded frames.")
                else:
                    series["timestamp"] = pd.Categorical(
                        series["timestamp"], categories=upto, ordered=True
                    )
                    series = series.sort_values("timestamp")
                    chart_cols = [c for c in ["p_flood", "risk_score"]
                                  if c in series.columns]
                    st.line_chart(
                        series.set_index("timestamp")[chart_cols],
                        height=280,
                    )
                    st.caption(
                        f"Frames {upto[0]} → {upto[-1]} UTC "
                        f"({len(upto)} of {len(timestamps)})."
                    )

        with right:
            st.subheader("Drivers (SHAP, plain words)")
            drivers = row.get("drivers")
            if not isinstance(drivers, (list, tuple)) or len(drivers) == 0:
                st.info("No driver attributions in this file.")
            else:
                try:
                    import matplotlib.pyplot as plt

                    labels, weights = [], []
                    for item in drivers:
                        if isinstance(item, (list, tuple)) and len(item) >= 2:
                            labels.append(str(item[0]))
                            weights.append(float(item[1]))
                    if not labels:
                        raise ValueError("unrecognised driver format")
                    order = sorted(range(len(weights)), key=lambda i: weights[i])
                    labels = [labels[i] for i in order]
                    weights = [weights[i] for i in order]

                    fig, ax = plt.subplots(figsize=(5, 0.6 * len(labels) + 1.4))
                    ax.barh(
                        labels, weights,
                        color=["#c0392b" if w >= 0 else "#2e6fb7" for w in weights],
                    )
                    ax.set_xlabel("contribution to p_flood")
                    ax.axvline(0, color="#333333", linewidth=0.8)
                    for y, w in enumerate(weights):
                        ax.text(w, y, f" {w:+.2f}", va="center", fontsize=9)
                    fig.tight_layout()
                    st.pyplot(fig, width="stretch")
                    plt.close(fig)
                except Exception as exc:  # noqa: BLE001
                    st.warning(f"Could not draw drivers ({exc}).")
                    st.write(drivers)

            st.subheader("Exposure")
            exposure = pd.DataFrame(
                [
                    {"Metric": "People", "Value": dash(row.get("people"), "{:,}")},
                    {"Metric": "Hospitals", "Value": dash(row.get("hospitals"), "{:,}")},
                    {"Metric": "Schools", "Value": dash(row.get("schools"), "{:,}")},
                    {"Metric": "Road (km)", "Value": dash(row.get("road_km"), "{:.1f}")},
                    {"Metric": "Pumps", "Value": dash(row.get("pumps"), "{:,}")},
                ]
            )
            st.dataframe(exposure, width="stretch", hide_index=True)

        st.markdown("---")
        st.subheader("Advisory")
        st.caption("AI-generated narration of model outputs. The models forecast; the AI explains.")
        adv = load_advisory(event_id, ward_id, ts)
        if not adv:
            st.info(
                f"No cached advisory for `{ward_id}` at {ts} "
                f"(`advisory_{ward_id}_{ts}.json` not present)."
            )
        else:
            a1, a2 = st.columns(2)
            a1.markdown("**English**")
            a1.write(adv.get("advisory_en") or "—")
            a2.markdown("**हिन्दी**")
            a2.write(adv.get("advisory_hi") or "—")

            actions = adv.get("actions") or []
            st.markdown("**Recommended actions**")
            if actions:
                for i, action in enumerate(actions, 1):
                    st.markdown(f"{i}. {action}")
            else:
                st.write("—")
            st.caption(
                f"Generated {dash(adv.get('generated'))} · "
                f"cached: {dash(adv.get('cached'))}"
            )


# ==========================================================================
# TAB 4 — VERIFICATION (the four proofs)
# ==========================================================================
with tab_verify:
    metrics, metrics_path = load_metrics()
    if not metrics:
        st.warning(
            "No `reports/metrics.json` found. Looked in:\n\n"
            + "\n".join(f"- `{p}`" for p in METRICS_CANDIDATES)
        )
    else:
        st.caption(f"Source: `{metrics_path}`")
        notes = metrics.get("notes") or {}
        if notes:
            st.info(" · ".join(f"**{k}**: {v}" for k, v in notes.items()))

        # ---- P-1 ablation ------------------------------------------------
        st.subheader("P-1 · Fusion works — ablation table")
        ablation = metrics.get("ablation") or []
        if not ablation:
            st.info("No ablation rows in metrics.json.")
        else:
            adf = pd.DataFrame(ablation)
            rename = {"config": "Config", "csi": "CSI", "pod": "POD",
                      "far": "FAR", "brier": "Brier"}
            adf = adf.rename(columns={k: v for k, v in rename.items()
                                      if k in adf.columns})
            st.dataframe(
                adf,
                width="stretch",
                hide_index=True,
                column_config={
                    "Config": st.column_config.TextColumn("Config", width="medium")
                },
            )
            if "CSI" in adf.columns and "Config" in adf.columns:
                st.bar_chart(adf.set_index("Config")[["CSI"]], height=240)
            st.caption("Higher CSI/POD is better; lower FAR/Brier is better.")

        st.markdown("---")

        # ---- P-2 reliability --------------------------------------------
        st.subheader("P-2 · Calibration is real — reliability diagram")
        reliability = metrics.get("reliability") or {}
        if not reliability:
            st.info("No reliability points in metrics.json.")
        else:
            try:
                import matplotlib.pyplot as plt

                fig, ax = plt.subplots(figsize=(6, 5))
                ax.plot([0, 1], [0, 1], "--", color="#888888",
                        label="perfect calibration (y = x)")
                for head, points in reliability.items():
                    pdf = pd.DataFrame(points)
                    if pdf.empty or "predicted" not in pdf or "observed" not in pdf:
                        continue
                    ax.plot(
                        pdf["predicted"], pdf["observed"],
                        marker="o", linewidth=1.8, label=head,
                    )
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                ax.set_xlabel("predicted probability")
                ax.set_ylabel("observed frequency")
                ax.set_title("Reliability")
                ax.legend(loc="upper left", fontsize=9)
                ax.grid(alpha=0.25)
                fig.tight_layout()
                cl, cr = st.columns([3, 2])
                cl.pyplot(fig, width="stretch")
                plt.close(fig)
                with cr:
                    for head, points in reliability.items():
                        st.markdown(f"**{head}**")
                        st.dataframe(
                            pd.DataFrame(points),
                            width="stretch",
                            hide_index=True,
                            height=240,
                        )
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Could not draw the reliability diagram ({exc}).")
                st.write(reliability)

        st.markdown("---")

        # ---- skill vs lead ----------------------------------------------
        st.subheader("Skill vs lead time")
        skill = metrics.get("skill_vs_lead") or []
        if not skill:
            st.info("No skill-vs-lead points in metrics.json.")
        else:
            sdf = pd.DataFrame(skill)
            if {"lead_h", "csi"}.issubset(sdf.columns):
                if "model" in sdf.columns:
                    pivot = sdf.pivot_table(
                        index="lead_h", columns="model", values="csi", aggfunc="mean"
                    ).sort_index()
                else:
                    pivot = sdf.set_index("lead_h")[["csi"]].sort_index()
                st.line_chart(pivot, height=300)
                st.caption("CSI against forecast lead (hours). Higher is better.")
            st.dataframe(sdf, width="stretch", hide_index=True)

        st.markdown("---")

        # ---- P-3 lead time vs CAP ---------------------------------------
        st.subheader("P-3 · Lead time gained over IMD CAP")
        leadtime = metrics.get("leadtime_vs_cap") or []
        if not leadtime:
            st.info("No lead-time-vs-CAP rows in metrics.json.")
        else:
            ldf = pd.DataFrame(leadtime)
            if "minutes_gained" in ldf.columns and len(ldf):
                st.metric(
                    "Mean minutes gained",
                    dash(float(ldf["minutes_gained"].mean()), "{:.0f} min"),
                )
            ldf = ldf.rename(
                columns={
                    "event": "Event",
                    "pravaah_crossing_utc": "PRAVAAH crossing (UTC)",
                    "imd_cap_sent_utc": "IMD CAP sent (UTC)",
                    "minutes_gained": "Minutes gained",
                    "matched_far": "Matched FAR",
                }
            )
            st.dataframe(ldf, width="stretch", hide_index=True)
            st.caption("Minutes gained is measured at matched false-alarm ratio.")
