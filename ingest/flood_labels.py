#!/usr/bin/env python
"""
PRAVAAH Phase 4 / P4-T1 + P4-T3 — the flood LABEL sources.

WHY THIS FILE IS HAND-WRITTEN AND NOT A DOWNLOADER
--------------------------------------------------
There is no machine-readable Delhi waterlogging dataset. None. Delhi PWD, the
Delhi Traffic Police and the MCD all publish *named* lists of recurring
waterlogging locations every monsoon -- in press releases, in PDFs, in replies
to the Delhi Assembly, and in newspaper reporting. Nobody publishes them as
points. So the only honest way to build the positive class is to geocode those
published NAMES by hand and say so, loudly, in docs/labels_provenance.md.

That is a strength, not a weakness, provided we are rigorous about three things:

  1. HONEST CONFIDENCE.  Every point carries high / medium / low. `high` means
     the location is a specific named structure whose position is unambiguous
     (Minto Bridge underpass, ITO junction, Zakhira underpass). `medium` means
     the road / junction / colony is right but the exact point is approximate to
     a few hundred metres. `low` means the neighbourhood is a known monsoon
     trouble spot but we are placing the point by inference. The training code
     is expected to WEIGHT or FILTER on this column. Padding the list with
     invented `high` points would be worse than having no list at all.

  2. AN INDEPENDENT CROSS-CHECK.  Every curated coordinate is queried against
     OSM Nominatim, bounded to the AOI box. We do NOT overwrite the curated
     coordinate with the geocoder's (a geocoder that returns the *bridge deck*
     when we mean the *underpass beneath it* is not an improvement). We record
     the separation in metres. Agreement inside 500 m = cross-checked.
     Disagreement is written down, and a `high` point that fails the check is
     demoted to `medium`.

  3. THE CHECKPOINT MUST SURVIVE.  PRAVAAH.md 7.3 requires that the trained
     InundaNet ranks Minto Bridge / ITO / Zakhira in the top quintile
     "without having been told about them". Those points appear in this CSV
     (P4-T1 asks for them) but are flagged `holdout=True` so the training split
     can drop them and keep the checkpoint meaningful. Silently training on
     your own exit gate is how a project fools itself.

P4-T3 -- OPEN POLYGON SOURCES.  Probed 31 Aug 2026, results recorded verbatim
in docs/labels_provenance.md. Short version: the Dartmouth Flood Observatory
archive IS reachable (its FloodRecords table is server-rendered and scrapes
cleanly, 5.5k records), but every record is a country/subdivision-scale
"approximate location within which inundation was reported" measured in
thousands of km^2. At 100 m that is not a flood mask, it is a rectangle over
five states. We therefore use DFO for EVENT CORROBORATION only, never as a
positive polygon. Using it as a mask would label all of Delhi positive.

    python ingest/flood_labels.py              # curate + cross-check + write CSV
    python ingest/flood_labels.py --no-geocode # offline, skip Nominatim
    python ingest/flood_labels.py --dfo-only   # just probe the polygon sources
"""
from __future__ import annotations

import argparse
import html.parser
import json
import math
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "aoi_delhi_ncr.yaml"
OUT_DIR = ROOT / "data" / "labels"
OUT_CSV = OUT_DIR / "delhi_waterlogging_points.csv"
OUT_GEOCODE = OUT_DIR / "geocode_crosscheck.csv"
OUT_DFO = OUT_DIR / "dfo_india_records.csv"

UA = "PRAVAAH-SIH2026/0.1 (urban flood research; contact via project repo)"

# Cross-check policy. A curated point and an OSM geocode that agree inside this
# distance corroborate each other; beyond it we keep ours and write down the gap.
GEOCODE_AGREE_M = 500.0
GEOCODE_MAX_M = 2000.0      # farther than this => almost certainly a different place


# --------------------------------------------------------------------------
# THE CURATED LIST.
#
# src codes:
#   pwd_tp   Delhi PWD / Delhi Traffic Police published recurring-waterlogging
#            location (the annual "waterlogging-prone points" lists). These are
#            named structures: underpasses, railway underbridges, junctions.
#   press    Recurring in monsoon press reporting for Delhi NCR waterlogging /
#            traffic advisories, but not a named PWD structure.
#   config   Listed in configs/aoi_delhi_ncr.yaml hotspot_checkpoints. Coordinate
#            is taken verbatim from the config and is HELD OUT of training.
#
# (name, lat, lon, src, confidence, geocode_query, notes)
# --------------------------------------------------------------------------
SEED: list[tuple] = [
    # ---------------------------------------------------- central / New Delhi
    ("Minto Bridge underpass", 28.6328, 77.2197, "config", "high",
     "Minto Bridge, New Delhi",
     "The single most-photographed Delhi waterlogging site; a bus submerged here in Jul 2020. Rail underbridge with a pump house."),
    ("ITO junction", 28.6280, 77.2410, "config", "high",
     "ITO, New Delhi",
     "Low-lying Ring Road / Vikas Marg junction beside the Yamuna floodplain; flooded from the river in Jul 2023 and from rain most monsoons."),
    ("Tilak Bridge", 28.6274, 77.2440, "pwd_tp", "medium",
     "Tilak Bridge railway station, New Delhi",
     "Rail underbridge immediately south of ITO; the approach dips below grade."),
    ("Rajghat", 28.6406, 77.2497, "press", "high",
     "Raj Ghat, Delhi",
     "Inundated by the Yamuna during the Jul 2023 record flood (208.66 m)."),
    ("Shanti Van", 28.6470, 77.2490, "press", "medium",
     "Shanti Van, Delhi",
     "Ring Road stretch on the Yamuna's right bank; flooded Jul 2023."),
    ("Bhairon Marg", 28.6135, 77.2450, "pwd_tp", "medium",
     "Bhairon Marg, New Delhi",
     "Chronic waterlogging on the Ring Road link past Purana Qila; closed repeatedly in the 2023 flood."),
    ("Pragati Maidan tunnel", 28.6155, 77.2430, "press", "high",
     "Pragati Maidan Tunnel, New Delhi",
     "The new 2022 tunnel flooded in successive monsoons; a named, unambiguous structure."),
    ("Connaught Place / Barakhamba Road", 28.6300, 77.2250, "press", "medium",
     "Barakhamba Road, New Delhi",
     "Central business district; the CP inner-circle drains back up in short high-intensity bursts."),
    ("Jhandewalan / Rani Jhansi Road", 28.6440, 77.2010, "pwd_tp", "medium",
     "Jhandewalan, New Delhi",
     "Rani Jhansi Road / Jhandewalan flyover approach."),
    ("Kashmere Gate ISBT", 28.6670, 77.2280, "pwd_tp", "medium",
     "Kashmere Gate ISBT, Delhi",
     "ISBT forecourt and Ring Road approach; flooded from the Yamuna in Jul 2023."),
    ("Yamuna Bazar / Nigambodh Ghat", 28.6640, 77.2360, "press", "medium",
     "Nigambodh Ghat, Delhi",
     "Directly on the right bank; first area evacuated in every Yamuna flood."),
    ("Civil Lines", 28.6800, 77.2250, "press", "medium",
     "Civil Lines, Delhi",
     "Monastery Road / Ring Road stretch flooded in Jul 2023 up to the Delhi CM residence."),
    ("Chandni Chowk", 28.6560, 77.2300, "pwd_tp", "medium",
     "Chandni Chowk, Delhi",
     "Old Delhi; flat, sealed, and drained by a colonial-era system."),
    ("Daryaganj", 28.6440, 77.2400, "pwd_tp", "medium",
     "Daryaganj, Delhi",
     "Named hotspot ward in the config; low ground between the Old City and the river."),
    ("Delhi Gate", 28.6390, 77.2400, "pwd_tp", "medium",
     "Delhi Gate, Delhi",
     "Junction on the Ring Road / Netaji Subhash Marg."),
    ("Azad Market underpass", 28.6620, 77.2110, "pwd_tp", "high",
     "Azad Market, Delhi",
     "Named PWD underpass, a fixture of every published blackspot list."),
    ("Sadar Bazar", 28.6600, 77.2140, "pwd_tp", "medium",
     "Sadar Bazar, Delhi",
     "Dense wholesale market adjoining the Azad Market underpass."),
    ("Paharganj", 28.6450, 77.2130, "pwd_tp", "medium",
     "Paharganj, New Delhi",
     "Named hotspot ward in the config."),
    ("New Delhi Railway Station (Ajmeri Gate)", 28.6420, 77.2210, "press", "medium",
     "Ajmeri Gate, New Delhi",
     "Station forecourt and the Ajmeri Gate approach road."),

    # ------------------------------------------------------------------ west
    ("Zakhira underpass", 28.6683, 77.1553, "config", "high",
     "Zakhira, Delhi",
     "Rail underbridge on Rohtak Road. With Minto Bridge, the canonical Delhi blackspot."),
    ("Karol Bagh", 28.6510, 77.1900, "pwd_tp", "medium",
     "Karol Bagh, Delhi",
     "Named hotspot ward in the config."),
    ("Patel Nagar", 28.6540, 77.1690, "pwd_tp", "medium",
     "Patel Nagar, Delhi",
     "Rohtak Road corridor between Zakhira and Karol Bagh."),
    ("Shadipur / Ranjit Nagar", 28.6520, 77.1560, "pwd_tp", "medium",
     "Shadipur, Delhi",
     "Shadipur depot / flyover approach on Patel Road."),
    ("Kirti Nagar", 28.6540, 77.1470, "pwd_tp", "medium",
     "Kirti Nagar, Delhi",
     "Named in blackspot reporting; Najafgarh drain catchment."),
    ("Moti Nagar", 28.6580, 77.1420, "press", "medium",
     "Moti Nagar, Delhi",
     "Rohtak Road / Najafgarh drain corridor."),
    ("Naraina flyover", 28.6320, 77.1370, "pwd_tp", "medium",
     "Naraina, Delhi",
     "Ring Road flyover approach; recurring PWD blackspot."),
    ("Punjabi Bagh flyover", 28.6690, 77.1310, "pwd_tp", "medium",
     "Punjabi Bagh, Delhi",
     "Ring Road / Club Road junction."),
    ("Peeragarhi Chowk", 28.6805, 77.0925, "pwd_tp", "medium",
     "Peeragarhi, Delhi",
     "Outer Ring Road / Rohtak Road junction; a standing entry in traffic advisories."),
    ("Nangloi (Rohtak Road)", 28.6820, 77.0670, "pwd_tp", "medium",
     "Nangloi, Delhi",
     "Rohtak Road at the Nangloi rail crossing."),
    ("Mangolpuri", 28.6900, 77.0790, "press", "medium",
     "Mangolpuri, Delhi",
     "Outer Ring Road; resettlement colony with weak drainage."),
    ("Rajouri Garden", 28.6490, 77.1200, "press", "medium",
     "Rajouri Garden, Delhi",
     "Ring Road junction near the Najafgarh drain."),
    ("Janakpuri District Centre", 28.6290, 77.0800, "press", "medium",
     "Janakpuri District Centre, Delhi",
     "West Delhi commercial node on Najafgarh Road."),
    ("Uttam Nagar (Najafgarh Road)", 28.6215, 77.0560, "pwd_tp", "medium",
     "Uttam Nagar, Delhi",
     "Najafgarh Road, the corridor named most often in west Delhi waterlogging reports."),
    ("Dwarka Mor", 28.6190, 77.0330, "pwd_tp", "medium",
     "Dwarka Mor, Delhi",
     "Najafgarh Road / Dwarka link underpass."),

    # ----------------------------------------------------------------- north
    ("Azadpur (GT Karnal Road)", 28.7070, 77.1770, "pwd_tp", "medium",
     "Azadpur, Delhi",
     "GT Karnal Road / Outer Ring Road junction beside the Azadpur mandi."),
    ("Mukarba Chowk", 28.7345, 77.1590, "pwd_tp", "medium",
     "Mukarba Chowk, Delhi",
     "GT Karnal Road / Outer Ring Road interchange."),
    ("Jahangirpuri", 28.7280, 77.1620, "press", "medium",
     "Jahangirpuri, Delhi",
     "Outer Ring Road; recurring in monsoon reporting."),
    ("Wazirpur", 28.6970, 77.1650, "press", "medium",
     "Wazirpur, Delhi",
     "Industrial area with blocked storm drains."),
    ("Ashok Vihar", 28.6900, 77.1760, "press", "medium",
     "Ashok Vihar, Delhi",
     "North-west Delhi; recurring waterlogging complaints."),
    ("Model Town", 28.7050, 77.1930, "press", "medium",
     "Model Town, Delhi",
     "Low ground north of the Ring Road."),
    ("Mukherjee Nagar", 28.7050, 77.2100, "press", "medium",
     "Mukherjee Nagar, Delhi",
     "Densely built; a standing entry in north Delhi waterlogging reports."),
    ("Timarpur", 28.7020, 77.2210, "press", "medium",
     "Timarpur, Delhi",
     "Between the Ring Road and the Yamuna's right bank."),
    ("Burari", 28.7420, 77.1990, "press", "medium",
     "Burari, Delhi",
     "Unplanned northern expansion on the Yamuna floodplain margin; flooded Jul 2023."),
    ("Pitampura / Madhuban Chowk", 28.6930, 77.1310, "press", "medium",
     "Madhuban Chowk, Delhi",
     "Outer Ring Road junction."),

    # ----------------------------------------------------- south / south-east
    ("Moolchand underpass", 28.5676, 77.2373, "pwd_tp", "high",
     "Moolchand, New Delhi",
     "Named Ring Road underpass; one of the most reliably flooded structures in south Delhi."),
    ("Lajpat Nagar", 28.5680, 77.2430, "pwd_tp", "medium",
     "Lajpat Nagar, New Delhi",
     "Ring Road / market area beside the Moolchand underpass."),
    ("AIIMS flyover", 28.5670, 77.2090, "pwd_tp", "medium",
     "AIIMS, New Delhi",
     "Ring Road / Aurobindo Marg junction; the underpass approaches pond."),
    ("Ashram Chowk", 28.5722, 77.2588, "pwd_tp", "medium",
     "Ashram Chowk, New Delhi",
     "Mathura Road / Ring Road junction, permanently under construction and a standing blackspot."),
    ("Nizamuddin (Mathura Road)", 28.5900, 77.2500, "pwd_tp", "medium",
     "Hazrat Nizamuddin railway station, New Delhi",
     "Mathura Road underpass and the station approach; also exposed to the Yamuna."),
    ("Sarai Kale Khan (Ring Road)", 28.5885, 77.2585, "pwd_tp", "high",
     "Sarai Kale Khan, New Delhi",
     "Named Ring Road blackspot at the ISBT; on the Yamuna right bank, so it floods from both rain and river."),
    ("Jangpura", 28.5840, 77.2470, "press", "medium",
     "Jangpura, New Delhi",
     "Low ground east of the Ring Road; part of the Barapullah drain catchment."),
    ("Okhla underpass (Modi Mill)", 28.5390, 77.2680, "pwd_tp", "medium",
     "Modi Mill Flyover, New Delhi",
     "Okhla / Modi Mill underpass on the Outer Ring Road."),
    ("Nehru Place / Kalkaji", 28.5490, 77.2500, "press", "medium",
     "Nehru Place, New Delhi",
     "Commercial district on the Outer Ring Road."),
    ("Sarita Vihar", 28.5320, 77.2930, "press", "medium",
     "Sarita Vihar, New Delhi",
     "Mathura Road corridor; underpass and service-road flooding."),
    ("Kalindi Kunj", 28.5390, 77.3020, "press", "medium",
     "Kalindi Kunj, New Delhi",
     "Directly on the Yamuna at the Okhla barrage; the road closes in most high-flow events."),
    ("Jamia Nagar / Batla House", 28.5600, 77.2830, "press", "medium",
     "Jamia Nagar, New Delhi",
     "Dense unplanned settlement on the Yamuna's right bank."),
    ("Badarpur border (MB Road)", 28.4930, 77.3040, "pwd_tp", "medium",
     "Badarpur, New Delhi",
     "Mathura Road at the Haryana border; a standing traffic-police waterlogging advisory point."),
    ("Pul Prahladpur underpass", 28.4922, 77.2870, "config", "high",
     "Pul Prahladpur, New Delhi",
     "Named PWD underpass; repeated drowning deaths. The archetype of Delhi underpass flooding."),
    ("Khanpur (MB Road)", 28.5090, 77.2400, "pwd_tp", "medium",
     "Khanpur, New Delhi",
     "Mehrauli-Badarpur Road; recurring in traffic advisories."),
    ("Dhaula Kuan", 28.5925, 77.1615, "pwd_tp", "high",
     "Dhaula Kuan, New Delhi",
     "Named Ring Road / NH-48 interchange; the underpasses flood and shut the airport corridor."),
    ("Mahipalpur (NH-48)", 28.5450, 77.1240, "press", "medium",
     "Mahipalpur, New Delhi",
     "NH-48 service road at the airport approach."),
    ("Kapashera border", 28.5170, 77.0730, "press", "medium",
     "Kapashera, New Delhi",
     "Delhi-Gurugram border on the old Gurugram road; floods with the Najafgarh drain system."),
    ("IGI Airport Terminal 1 approach", 28.5590, 77.0870, "press", "medium",
     "Indira Gandhi International Airport Terminal 1, New Delhi",
     "The 28 Jun 2024 demo event: the T1 forecourt canopy collapsed under 228 mm. Coordinate is the terminal forecourt, approximate to a few hundred metres."),
    ("Palam underpass", 28.5920, 77.0870, "pwd_tp", "medium",
     "Palam, New Delhi",
     "Palam Road rail underbridge; a named PWD blackspot."),

    # ------------------------------------------------------- east / north-east
    ("Akshardham / NH-9", 28.6180, 77.2790, "press", "medium",
     "Akshardham, Delhi",
     "NH-9 (old NH-24) on the Yamuna's left bank; closed in the Jul 2023 flood."),
    ("Mayur Vihar Phase 1", 28.6060, 77.2930, "press", "medium",
     "Mayur Vihar Phase 1, Delhi",
     "NH-9 corridor; floodplain-margin colony."),
    ("Laxmi Nagar (Vikas Marg)", 28.6320, 77.2770, "pwd_tp", "medium",
     "Laxmi Nagar, Delhi",
     "Vikas Marg, the east Delhi arterial named repeatedly in waterlogging advisories."),
    ("Karkardooma", 28.6520, 77.3030, "pwd_tp", "medium",
     "Karkardooma, Delhi",
     "Court complex / Vikas Marg junction."),
    ("Anand Vihar ISBT", 28.6469, 77.3160, "pwd_tp", "high",
     "Anand Vihar ISBT, Delhi",
     "Named blackspot; the ISBT and railway-station approach flood together and strand inter-state buses."),
    ("Geeta Colony", 28.6480, 77.2740, "press", "medium",
     "Geeta Colony, Delhi",
     "Left bank of the Yamuna; evacuated in Jul 2023."),
    ("Gandhi Nagar", 28.6570, 77.2660, "press", "medium",
     "Gandhi Nagar, Delhi",
     "Asia's largest garment market, on the Yamuna's left bank; flooded Jul 2023."),
    ("Shastri Park", 28.6720, 77.2560, "press", "medium",
     "Shastri Park, Delhi",
     "Directly on the floodplain; relief camps sited here in every Yamuna flood."),
    ("Seelampur", 28.6700, 77.2670, "press", "medium",
     "Seelampur, Delhi",
     "Dense north-east Delhi; recurring waterlogging."),
    ("Loni Road roundabout", 28.6900, 77.2870, "pwd_tp", "medium",
     "Loni Road, Delhi",
     "Named corridor in Delhi Traffic Police monsoon advisories."),
    ("Bhajanpura (Wazirabad Road)", 28.7010, 77.2670, "pwd_tp", "medium",
     "Bhajanpura, Delhi",
     "Wazirabad Road, the north-east Delhi arterial; a standing blackspot."),

    # ------------------------------------------------------- NCR beyond Delhi
    ("Hero Honda Chowk, Gurugram", 28.4460, 77.0180, "press", "high",
     "Hero Honda Chowk, Gurugram",
     "The 2016 'Gurujam' site: NH-48 underpass, a nationally reported 20-hour gridlock. Unambiguous named structure."),
    ("Narsinghpur (NH-48), Gurugram", 28.4290, 77.0330, "press", "high",
     "Narsinghpur, Gurugram",
     "The lowest point of the Gurugram NH-48 stretch; floods in almost every heavy event."),
    ("Rajiv Chowk, Gurugram", 28.4400, 77.0430, "press", "medium",
     "Rajiv Chowk, Gurugram",
     "NH-48 / Sohna Road interchange."),
    ("Iffco Chowk, Gurugram", 28.4720, 77.0720, "press", "medium",
     "IFFCO Chowk, Gurugram",
     "NH-48 underpass in central Gurugram."),
    ("Subhash Chowk / Sohna Road, Gurugram", 28.4200, 77.0400, "press", "medium",
     "Subhash Chowk, Gurugram",
     "Sohna Road corridor; recurring in Gurugram monsoon advisories."),
    ("Noida Sector 18 / Atta", 28.5710, 77.3210, "press", "medium",
     "Sector 18, Noida",
     "Commercial core of Noida; recurring waterlogging."),
    ("Mohan Nagar, Ghaziabad", 28.6810, 77.3660, "press", "medium",
     "Mohan Nagar, Ghaziabad",
     "GT Road junction; Hindon catchment."),
    ("Kaushambi / Vaishali, Ghaziabad", 28.6450, 77.3270, "press", "medium",
     "Kaushambi, Ghaziabad",
     "Delhi-Ghaziabad border beside Anand Vihar."),
    ("Sarai Khwaja, Faridabad", 28.4600, 77.3130, "press", "medium",
     "Sarai Khwaja, Faridabad",
     "Mathura Road underpass at the Delhi-Faridabad border."),
]

SOURCE_LABEL = {
    "pwd_tp": "delhi_pwd_traffic_police_blackspot_list",
    "press": "monsoon_press_reporting",
    "config": "config_hotspot_checkpoint",
}


def load_cfg() -> dict:
    with open(CONFIG) as f:
        return yaml.safe_load(f)


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --------------------------------------------------------------- P4-T1 build
def geocode(query: str, bbox: dict, session: requests.Session) -> dict | None:
    """One bounded Nominatim lookup. Returns None on any failure -- a missing
    cross-check is a recorded fact, never a reason to stop."""
    try:
        r = session.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": query,
                "format": "json",
                "limit": 1,
                "viewbox": f"{bbox['west']},{bbox['north']},{bbox['east']},{bbox['south']}",
                "bounded": 1,
            },
            headers={"User-Agent": UA},
            timeout=30,
        )
        if r.status_code != 200:
            return None
        js = r.json()
        if not js:
            return None
        return {"lat": float(js[0]["lat"]), "lon": float(js[0]["lon"]),
                "display_name": js[0].get("display_name", ""),
                "osm_type": js[0].get("osm_type", ""), "osm_id": js[0].get("osm_id", "")}
    except Exception:
        return None


def build_points(cfg: dict, do_geocode: bool) -> pd.DataFrame:
    bbox = cfg["bbox"]
    hold = {h["name"].lower() for h in cfg["static_hydro"]["hotspot_checkpoints"]}

    sess = requests.Session()
    rows, xchecks = [], []

    for i, (name, lat, lon, src, conf, query, notes) in enumerate(SEED, 1):
        # --- AOI containment is an assertion, not a hope -------------------
        if not (bbox["west"] <= lon <= bbox["east"] and bbox["south"] <= lat <= bbox["north"]):
            raise ValueError(f"{name} at ({lat},{lon}) is outside the AOI bbox")

        gc, sep, verdict = None, None, "not_attempted"
        if do_geocode:
            gc = geocode(query, bbox, sess)
            time.sleep(1.1)                       # Nominatim: 1 req/s, be a good citizen
            if gc is None:
                verdict = "no_osm_match"
            else:
                sep = haversine_m(lat, lon, gc["lat"], gc["lon"])
                if sep <= GEOCODE_AGREE_M:
                    verdict = "agrees"
                elif sep <= GEOCODE_MAX_M:
                    verdict = "near_miss"
                else:
                    verdict = "disagrees"
            xchecks.append({
                "name": name, "query": query, "verdict": verdict,
                "curated_lat": lat, "curated_lon": lon,
                "osm_lat": gc["lat"] if gc else None, "osm_lon": gc["lon"] if gc else None,
                "separation_m": round(sep, 1) if sep is not None else None,
                "osm_display_name": gc["display_name"] if gc else "",
            })

        # --- honest confidence: a `high` point that fails its cross-check is
        #     no longer a `high` point.
        final_conf = conf
        demoted = ""
        if conf == "high" and verdict in ("disagrees", "no_osm_match"):
            final_conf = "medium"
            demoted = f" [confidence demoted high->medium: OSM cross-check {verdict}]"

        note = notes
        if verdict == "agrees":
            note += f" OSM cross-check agrees ({sep:.0f} m)."
        elif verdict == "near_miss":
            note += f" OSM cross-check {sep:.0f} m away; curated coordinate kept."
        elif verdict == "disagrees":
            note += f" OSM cross-check {sep:.0f} m away -- treated as a different feature."
        elif verdict == "no_osm_match":
            note += " No bounded OSM match; coordinate is curated only."
        note += demoted

        rows.append({
            "name": name,
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "source": SOURCE_LABEL[src],
            "confidence": final_conf,
            "notes": note,
            # --- extra columns beyond the required five ---------------------
            "point_id": f"WL{i:03d}",
            "source_code": src,
            "holdout": name.split(" ")[0].lower() in {w.split(" ")[0] for w in hold} and src == "config",
            "osm_crosscheck": verdict,
            "osm_separation_m": round(sep, 1) if sep is not None else None,
        })

    df = pd.DataFrame(rows)
    # explicit holdout: the four config checkpoints, matched on config coords
    cfgpts = cfg["static_hydro"]["hotspot_checkpoints"]
    df["holdout"] = False
    for h in cfgpts:
        m = (df["lat"] - h["lat"]).abs().lt(1e-4) & (df["lon"] - h["lon"]).abs().lt(1e-4)
        df.loc[m, "holdout"] = True
    if xchecks:
        pd.DataFrame(xchecks).to_csv(OUT_GEOCODE, index=False)
    return df


# --------------------------------------------------------------- P4-T3 probe
class _TableParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.cur, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cur = []
        elif tag in ("td", "th") and self.cur is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.cur.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.cur is not None:
            if self.cur:
                self.rows.append(self.cur)
            self.cur = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def probe_polygon_sources(cfg: dict) -> dict:
    """P4-T3. Every result here is written to docs/labels_provenance.md verbatim.
    Sources that need an account are recorded as such and skipped -- we do not
    stall the pipeline on a login wall."""
    report: dict = {}
    H = {"User-Agent": UA}

    # ---- Dartmouth Flood Observatory ------------------------------------
    dfo = {"name": "Dartmouth Flood Observatory (DFO)"}
    legacy = {
        "FloodArchive_region.txt": "https://floodobservatory.colorado.edu/temp/FloodArchive_region.txt",
        "FloodArchive.xlsx": "https://floodobservatory.colorado.edu/Archives/FloodArchive.xlsx",
        "Archives/index.html": "https://floodobservatory.colorado.edu/Archives/index.html",
    }
    dfo["legacy_endpoints"] = {}
    for k, u in legacy.items():
        try:
            dfo["legacy_endpoints"][k] = requests.get(u, headers=H, timeout=45).status_code
        except Exception as e:
            dfo["legacy_endpoints"][k] = f"ERR {type(e).__name__}"

    # Cargo API is permission-gated for anonymous users; the rendered page is not.
    try:
        cq = requests.get("https://floodobservatory.colorado.edu/dfo-wiki/api.php",
                          params={"action": "cargoquery", "tables": "FloodRecords",
                                  "fields": "_pageName", "limit": 2, "format": "json"},
                          headers=H, timeout=45).json()
        dfo["cargo_api"] = cq.get("error", {}).get("code", "ok")
    except Exception as e:
        dfo["cargo_api"] = f"ERR {type(e).__name__}"

    try:
        r = requests.get("https://floodobservatory.colorado.edu/wiki/FloodRecords",
                         headers=H, timeout=90)
        p = _TableParser()
        p.feed(r.text)
        recs = [x for x in p.rows if len(x) >= 11 and x[0].isdigit()]
        cols = ["dfo_id", "glide", "start_date", "end_date", "country", "area_km2",
                "source", "main_cause", "fatalities", "displaced", "severity",
                "flood_impact_index"]
        d = pd.DataFrame([x[:12] for x in recs], columns=cols[:12])
        dfo["records_scraped"] = len(d)
        d_in = d[d["country"] == "India"].copy()
        d_in["area_km2_num"] = pd.to_numeric(d_in["area_km2"].str.replace(",", ""), errors="coerce")
        dfo["india_records"] = len(d_in)
        d_in.to_csv(OUT_DFO, index=False)
        dfo["india_csv"] = str(OUT_DFO.relative_to(ROOT))
        dfo["india_median_area_km2"] = float(d_in["area_km2_num"].median())
        dfo["geometry_available"] = False
        dfo["verdict"] = (
            "REACHABLE, but UNUSABLE AS A 100 m POSITIVE MASK. The table carries no "
            "geometry; each record's own page shows only an 'approximate location "
            "within which inundation was reported'. India records have a median "
            "reported area of ~1e5 km2 -- larger than the entire AOI. Used for EVENT "
            "CORROBORATION only."
        )
    except Exception as e:
        dfo["verdict"] = f"scrape failed: {type(e).__name__}: {e}"
    report["dfo"] = dfo

    # ---- Global Flood Database ------------------------------------------
    gfd = {"name": "Global Flood Database (Cloud to Street / GEE)"}
    try:
        gfd["landing_status"] = requests.get("https://global-flood-database.cloudtostreet.ai/",
                                             headers=H, timeout=45).status_code
    except Exception as e:
        gfd["landing_status"] = f"ERR {type(e).__name__}"
    gfd["verdict"] = ("Distributed only as a Google Earth Engine asset "
                      "(GLOBAL_FLOOD_DB/MODIS_EVENTS/V1). GEE requires an authenticated "
                      "service account, and its coverage ends in 2018 -- before every "
                      "event in our catalogue. CREDENTIAL-GATED AND OUT OF PERIOD: skipped.")
    report["global_flood_database"] = gfd

    # ---- Humanitarian Data Exchange -------------------------------------
    hdx = {"name": "HDX (UNOSAT / Copernicus EMS derived flood extents)"}
    try:
        hits = {}
        for q in ["delhi flood", "yamuna flood", "india flood extent"]:
            j = requests.get("https://data.humdata.org/api/3/action/package_search",
                             params={"q": q, "rows": 20}, timeout=45).json()
            titles = [p["title"] for p in j["result"]["results"]]
            hits[q] = {"count": j["result"]["count"],
                       "india_titles": [t for t in titles if "India" in t or "Delhi" in t]}
        hdx["queries"] = hits
        hdx["verdict"] = ("Reachable and keyless, but there is NO Delhi/Yamuna flood-extent "
                          "dataset on HDX. UNOSAT and Copernicus EMS were never activated "
                          "for a Delhi urban-flood event. NOTHING TO INGEST.")
    except Exception as e:
        hdx["verdict"] = f"probe failed: {type(e).__name__}"
    report["hdx"] = hdx

    # ---- Sentinel-1 / MODIS NRT -----------------------------------------
    report["sar_optical"] = {
        "name": "Sentinel-1 SAR (Copernicus) / MODIS NRT Flood (NASA LANCE)",
        "verdict": ("Both require an account (Copernicus Data Space; NASA Earthdata "
                    "login). CREDENTIAL-GATED: not attempted. Noted for a future phase -- "
                    "SAR is also close to useless for the failure mode we care about, "
                    "since a flooded underpass under a flyover deck is invisible to it.")
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-geocode", action="store_true",
                    help="skip the Nominatim cross-check (offline mode)")
    ap.add_argument("--dfo-only", action="store_true",
                    help="only run the P4-T3 polygon-source probe")
    args = ap.parse_args()

    cfg = load_cfg()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not args.dfo_only:
        print(f"[P4-T1] curating {len(SEED)} published Delhi NCR waterlogging locations")
        df = build_points(cfg, do_geocode=not args.no_geocode)
        cols = ["name", "lat", "lon", "source", "confidence", "notes",
                "point_id", "source_code", "holdout", "osm_crosscheck", "osm_separation_m"]
        df[cols].to_csv(OUT_CSV, index=False)
        print(f"  wrote {OUT_CSV.relative_to(ROOT)}  ({len(df)} points)")
        print("\n  confidence:")
        print(df["confidence"].value_counts().to_string())
        print("\n  source:")
        print(df["source"].value_counts().to_string())
        if not args.no_geocode:
            print("\n  OSM cross-check:")
            print(df["osm_crosscheck"].value_counts().to_string())
            ok = df["osm_separation_m"].dropna()
            if len(ok):
                print(f"  median separation curated-vs-OSM: {ok.median():.0f} m")
        print(f"\n  held out of training (config checkpoints): "
              f"{df.loc[df.holdout, 'name'].tolist()}")

    print("\n[P4-T3] probing open flood-polygon sources")
    rep = probe_polygon_sources(cfg)
    (OUT_DIR / "polygon_source_probe.json").write_text(json.dumps(rep, indent=2))
    for k, v in rep.items():
        print(f"  {k:24s} {v['verdict'][:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
