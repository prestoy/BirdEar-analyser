# api.py - kjøres på RPi #1 sammen med BirdMicAnalyser
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from typing import Optional
import sqlite3
import yaml
import os
import httpx
import json
from datetime import datetime, timezone
import zoneinfo

CONFIG = "/home/e33admin/apps/BirdEar-analyser/config-default.yaml"


app = FastAPI()
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://192.168.1.62:8002",
        "http://birdmic-player.prestoy.cc",
        "https://birdmic-player.prestoy.cc",
        "http://birdear-player.prestoy.cc",
        "https://birdear-player.prestoy.cc",
        "http://birdmic-api.prestoy.cc",
        "https://birdmic-api.prestoy.cc",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def load_config():
    with open(CONFIG) as f:
        return yaml.safe_load(f)

def to_local(iso_str: str) -> str:
    """Konverter ISO UTC-streng fra Grafana til lokal tid (Europe/Oslo)."""
    tz_oslo = zoneinfo.ZoneInfo("Europe/Oslo")
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.astimezone(tz_oslo).strftime("%Y-%m-%dT%H:%M:%S")

def get_db():
    config = load_config()
    conn = sqlite3.connect(config["db-path"])
    conn.row_factory = sqlite3.Row
    return conn


# ----------------------------------------------------------------
# Filterkonfigurasjon
# ----------------------------------------------------------------
FILTER_DIR = "/home/e33admin/apps/BirdEar-analyser/kilder"
FILTERTABELL_PATH = f"{FILTER_DIR}/sjetnmarka_filtertabell.json"
OVERSTYRING_PATH  = f"{FILTER_DIR}/sjetnmarka_filtertabell_overstyring.json"

def load_filter():
    """Bygg opp oppslagsdicts for rask filtrering."""
    with open(FILTERTABELL_PATH, encoding="utf-8") as f:
        filtertabell = json.load(f)
    with open(OVERSTYRING_PATH, encoding="utf-8") as f:
        overstyring = json.load(f)

    # Hovedfilter: {vitenskapelig_navn: {mnd: {status, min_konfidens}}}
    hoved: dict = {}
    for art in filtertabell:
        mnd_dict = {}
        for m in art.get("maaneder", []):
            mnd_dict[m["mnd"]] = {
                "status": m["status"],
                "min_konfidens": m.get("min_konfidens"),
            }
        hoved[art["vitenskapelig_navn"]] = mnd_dict

    # Overstyring: {vitenskapelig_navn: {ekskluder_alle, ekskluderte_mnder}}
    overstyr: dict = {}
    for art in overstyring:
        navn = art["vitenskapelig_navn"]
        if art.get("ekskluder_alle_maaneder"):
            overstyr[navn] = {"ekskluder_alle": True, "mnder": set()}
        else:
            ekskl_mnder = {
                m["mnd"] for m in art.get("maaneder", [])
                if m.get("status") == "ekskluder"
            }
            overstyr[navn] = {"ekskluder_alle": False, "mnder": ekskl_mnder}

    return hoved, overstyr


def should_exclude(scientific_name: str, maaned: int,
                   hoved: dict, overstyr: dict) -> tuple[bool, float | None]:
    """
    Returner (skal_ekskluderes, min_konfidens).
    min_konfidens er None hvis arten ikke er i filteret (bruk API-default).
    """
    # 1. Sjekk overstyring
    if scientific_name in overstyr:
        o = overstyr[scientific_name]
        if o["ekskluder_alle"] or maaned in o["mnder"]:
            return True, None

    # 2. Sjekk hovedfilter
    if scientific_name in hoved:
        mnd_info = hoved[scientific_name].get(maaned)
        if mnd_info:
            if mnd_info["status"] == "ekskluder":
                return True, None
            return False, mnd_info["min_konfidens"]
        else:
            # Arten finnes i filteret men ikke for denne måneden — ekskluder
            return True, None

    # 3. Arten er ikke i noen filter — inkluder med API-default konfidens
    return False, None


# ----------------------------------------------------------------
# Hjelpefunksjon: hent norsk navn fra Artsdatabanken (med cache)
# ----------------------------------------------------------------
import httpx
_norwegian_name_cache: dict = {}

def get_norwegian_name(scientific_name: str) -> str:
    if scientific_name in _norwegian_name_cache:
        return _norwegian_name_cache[scientific_name]
    try:
        r1 = httpx.get(
            "https://artsdatabanken.no/Api/Taxon/ScientificName",
            params={"ScientificName": scientific_name},
            timeout=5.0
        )
        r1.raise_for_status()
        data1 = r1.json()
        if not data1:
            _norwegian_name_cache[scientific_name] = scientific_name
            return scientific_name
        taxon_id = data1[0].get("taxonID")
        if not taxon_id:
            _norwegian_name_cache[scientific_name] = scientific_name
            return scientific_name
        r2 = httpx.get(
            f"https://artsdatabanken.no/Api/Taxon/{taxon_id}",
            timeout=5.0
        )
        r2.raise_for_status()
        data2 = r2.json()
        preferred = data2.get("PreferredVernacularName")
        norwegian_name = (
            preferred["vernacularName"].capitalize()
            if preferred and preferred.get("vernacularName")
            else scientific_name
        )
    except Exception:
        norwegian_name = scientific_name
    _norwegian_name_cache[scientific_name] = norwegian_name
    return norwegian_name

##################################################################

#  GRAFANA-SPESIFIKE QUERIES
##################################################################

config = load_config()
MIN_CONF = config["analyse"]["min_confidence_display"]
AUDIO_DIR = config["audio-path"]


# ----------------------------------------------------------------
# 9. Matrise: antall deteksjoner per art per time (pivotert)
#    Aggregerer over flere dager (from_date til to_date).
#    Filtrerer basert på filtertabell og overstyring.
# ----------------------------------------------------------------
@app.get("/detections/matrix")
def get_detections_matrix(
    from_date: str,
    to_date: str,
    min_conf: float = MIN_CONF
):
    # Konverter dato på grunnlag av locale
    from_date = to_local(from_date)
    to_date = to_local(to_date)

    hoved, overstyr = load_filter()
 
    conn = get_db()
    rows = conn.execute(
        """SELECT scientific_name,
                  CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                  CAST(strftime('%m', timestamp) AS INTEGER) as month,
                  confidence
           FROM detections
           WHERE timestamp BETWEEN ? AND ?
           ORDER BY scientific_name, hour""",
        (from_date, to_date)
    ).fetchall()
    conn.close()

    species_hours: dict = {}
    for row in rows:
        name = row["scientific_name"]
        hour = row["hour"]
        maaned = row["month"]
        confidence = row["confidence"]
 
        ekskluder, art_min_konf = should_exclude(name, maaned, hoved, overstyr)
        if ekskluder:
            continue
 
        gjeldende_min_konf = art_min_konf if art_min_konf is not None else min_conf
        if confidence < gjeldende_min_konf:
            continue
 
        if name not in species_hours:
            species_hours[name] = {}
        species_hours[name][hour] = species_hours[name].get(hour, 0) + 1
 
    # Sorter etter totalt antall deteksjoner
    sorted_species = sorted(
        species_hours.keys(),
        key=lambda s: sum(species_hours[s].values()),
        reverse=True
    )
 
    # Pivot til flat liste
    result = []
    for name in sorted_species:
        row_dict = {}
        for h in range(24):
            count = species_hours[name].get(h, 0)
            row_dict[f"{h:02d}"] = count if count > 0 else None
        row_dict["!art"] = get_norwegian_name(name)
        row_dict["vitenskapelig_navn"] = name
        result.append(row_dict)
 
    return result

# ----------------------------------------------------------------
# 10. Matrise med prosentverdier: deteksjoner per art per time
#     som prosent av totalt antall deteksjoner i perioden.
#     Brukes av Grafana Table-panel med absolutte terskler
#     som reelt sett representerer prosentandeler.
# ----------------------------------------------------------------
@app.get("/detections/matrix_percentage")
def get_detections_matrix_percentage(
    from_date: str,
    to_date: str,
    min_conf: float = MIN_CONF
):
    # Konverter dato på grunnlag av locale
    from_date = to_local(from_date)
    to_date = to_local(to_date)

    hoved, overstyr = load_filter()

    conn = get_db()
    rows = conn.execute(
        """SELECT scientific_name,
                  CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                  CAST(strftime('%m', timestamp) AS INTEGER) as month,
                  confidence
           FROM detections
           WHERE timestamp BETWEEN ? AND ?
           ORDER BY scientific_name, hour""",
        (from_date, to_date)
    ).fetchall()
    conn.close()

    # Bygg opp dict med filtrering per art og måned
    species_hours: dict = {}
    for row in rows:
        name = row["scientific_name"]
        hour = row["hour"]
        maaned = row["month"]
        confidence = row["confidence"]

        ekskluder, art_min_konf = should_exclude(name, maaned, hoved, overstyr)
        if ekskluder:
            continue

        gjeldende_min_konf = art_min_konf if art_min_konf is not None else min_conf
        if confidence < gjeldende_min_konf:
            continue

        if name not in species_hours:
            species_hours[name] = {}
        species_hours[name][hour] = species_hours[name].get(hour, 0) + 1

    # Finn max-verdi på tvers av alle arter og timer
    max_count = max(
        (count for hours in species_hours.values() for count in hours.values()),
        default=1
    )

    # Sorter etter totalt antall deteksjoner
    sorted_species = sorted(
        species_hours.keys(),
        key=lambda s: sum(species_hours[s].values()),
        reverse=True
    )

    # Pivot til flat liste med prosentverdier
    result = []
    for name in sorted_species:
        row_dict = {}
        for h in range(24):
            count = species_hours[name].get(h, 0)
            if count > 0:
                row_dict[f"{h:02d}"] = round((count / max_count) * 100, 1)
            else:
                row_dict[f"{h:02d}"] = None
        row_dict["!art"] = get_norwegian_name(name)
        result.append(row_dict)

    return result

# ----------------------------------------------------------------
# 11. Deteksjoner per time: filtrert og aggregert
#     Bruker samme filterlogikk som /detections/matrix.
#     Returnerer antall deteksjoner per time for et tidsrom.
#     Brukes av Grafana Bar chart-panelet.
# ----------------------------------------------------------------
@app.get("/detections/by_hour")
def get_detections_by_hour(
    from_date: str,
    to_date: str,
    min_conf: float = MIN_CONF
):
    # Konverter dato på grunnlag av locale
    from_date = to_local(from_date)
    to_date = to_local(to_date)

    hoved, overstyr = load_filter()
    conn = get_db()
    rows = conn.execute(
        """SELECT scientific_name,
                  CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                  CAST(strftime('%m', timestamp) AS INTEGER) as month,
                  confidence
           FROM detections
           WHERE timestamp BETWEEN ? AND ?
           ORDER BY hour""",
        (from_date, to_date)
    ).fetchall()
    conn.close()

    # Tell deteksjoner per time med filtrering
    hour_counts: dict = {}
    for row in rows:
        name = row["scientific_name"]
        hour = row["hour"]
        maaned = row["month"]
        confidence = row["confidence"]

        ekskluder, art_min_konf = should_exclude(name, maaned, hoved, overstyr)
        if ekskluder:
            continue

        gjeldende_min_konf = art_min_konf if art_min_konf is not None else min_conf
        if confidence < gjeldende_min_konf:
            continue

        hour_counts[hour] = hour_counts.get(hour, 0) + 1

    # Returner alle 24 timer, også de uten deteksjoner
    return [
        {"time": f"{h:02d}", "detections": hour_counts.get(h) or None}
        for h in range(24)
    ]


# ----------------------------------------------------------------
# 12. Artsliste med antall deteksjoner over konfidensgrense
#     Ufiltrert — viser alle arter i perioden.
#     Sortert etter totalt antall deteksjoner.
# ----------------------------------------------------------------
@app.get("/detections/species_count")
def get_species_count(
    from_date: str,
    to_date: str,
    min_conf: float = MIN_CONF
):

    conn = get_db()
    rows = conn.execute(
        """SELECT scientific_name,
                  COUNT(*) as count
           FROM detections
           WHERE timestamp BETWEEN ? AND ?
           AND confidence >= ?
           GROUP BY scientific_name
           ORDER BY count DESC""",
        (from_date, to_date, min_conf)
    ).fetchall()
    conn.close()

    return [
        {
            "art": get_norwegian_name(row["scientific_name"]),
            "vitenskapelig_navn": row["scientific_name"],
            "antall": row["count"]
        }
        for row in rows
    ]


# ----------------------------------------------------------------
# 13. Liste over lydfiler for en art i en periode
#     Valgfri hour-parameter filtrerer på time i døgnet
#     på tvers av hele perioden.
# ----------------------------------------------------------------
@app.get("/detections/recordings")
def get_recordings(
    from_date: str,
    to_date: str,
    scientific_name: str,
    min_conf: float = MIN_CONF,
    hour: Optional[int] = None
):
    conn = get_db()

    if hour is not None:
        rows = conn.execute(
            """SELECT timestamp, recording, start_time, end_time, confidence
               FROM detections
               WHERE timestamp BETWEEN ? AND ?
               AND scientific_name = ?
               AND confidence >= ?
               AND CAST(strftime('%H', timestamp) AS INTEGER) = ?
               ORDER BY confidence DESC""",
            (from_date, to_date, scientific_name, min_conf, hour)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT timestamp, recording, start_time, end_time, confidence
               FROM detections
               WHERE timestamp BETWEEN ? AND ?
               AND scientific_name = ?
               AND confidence >= ?
               ORDER BY confidence DESC""",
            (from_date, to_date, scientific_name, min_conf)
        ).fetchall()

    conn.close()

    return [
        {
            "timestamp": row["timestamp"],
            "recording": row["recording"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "confidence": round(row["confidence"], 3),
            "url": f"/audio/{row['recording']}"
        }
        for row in rows
    ]


# ----------------------------------------------------------------
# 14. Server lydfiler fra NAS
# ----------------------------------------------------------------
@app.get("/audio/{filename}")
def serve_audio(filename: str):
    filepath = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Lydfil ikke funnet")
    return FileResponse(filepath, media_type="audio/mpeg")


# ----------------------------------------------------------------
# 15. Deteksjoner per time for én art i en periode
#     Brukes av Grafana Bar chart drill-down panel.
# ----------------------------------------------------------------
@app.get("/detections/species_by_hour")
def get_species_by_hour(
    from_date: str,
    to_date: str,
    scientific_name: str,
    min_conf: float = MIN_CONF
):
    # Konverter dato på grunnlag av locale
    from_date = to_local(from_date)
    to_date = to_local(to_date)

    conn = get_db()
    rows = conn.execute(
        """SELECT CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                  COUNT(*) as count
           FROM detections
           WHERE timestamp BETWEEN ? AND ?
           AND scientific_name = ?
           AND confidence >= ?
           GROUP BY hour
           ORDER BY hour""",
        (from_date, to_date, scientific_name, min_conf)
    ).fetchall()
    conn.close()

    hour_counts = {row["hour"]: row["count"] for row in rows}

    return [
        {"time": f"{h:02d}", "detections": hour_counts.get(h) or None}
        for h in range(24)
    ]