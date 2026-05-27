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

CONFIG = "/home/e33admin/apps/BirdMicAnalyser/config-default.yaml"
AUDIO_DIR = "/mnt/nas-e33_felles/birdmic/audioarkiv"

app = FastAPI()
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://birdear-api.prestoy.cc",
        "https://birdear-api.prestoy.cc",
        "http://birdear-player.prestoy.cc",
        "https://birdear-player.prestoy.cc",    
        "http://192.168.1.62:8002",
    ],
    allow_methods=["GET"],
    allow_headers=["*"],
)

def to_local(iso_str: str) -> str:
    """Konverter ISO UTC-streng fra Grafana til lokal tid (Europe/Oslo)."""
    tz_oslo = zoneinfo.ZoneInfo("Europe/Oslo")
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return dt.astimezone(tz_oslo).strftime("%Y-%m-%dT%H:%M:%S")

def load_config():
    with open(CONFIG) as f:
        return yaml.safe_load(f)

def get_db():
    config = load_config()
    conn = sqlite3.connect(config["db-path"])
    conn.row_factory = sqlite3.Row
    return conn

# ----------------------------------------------------------------
# 1. Kalender: datoer med deteksjoner for en gitt måned
# ----------------------------------------------------------------
@app.get("/detections/days")
def get_detection_days(year: int, month: int):
    from datetime import datetime, timedelta
    start_date = f"{year}-{month:02d}-01"
    end_date = (datetime.strptime(start_date, "%Y-%m-%d") + timedelta(days=31)).replace(day=1).strftime("%Y-%m-%d")
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT DATE(timestamp) as d FROM detections WHERE DATE(timestamp) BETWEEN ? AND ?",
        (start_date, end_date)
    ).fetchall()
    conn.close()
    return [row["d"] for row in rows]

# ----------------------------------------------------------------
# 2. Dagsvisning: art + time for en dato (til histogram)
# ----------------------------------------------------------------
# PATCH 13-05-2026: Erstatt eksisterende /detections/by_date med denne versjonen.
# Endringen: confidence er lagt til i SELECT og returverdien,
# slik at show_filtered_detections kan filtrere på artsspecifikk terskel.
# ----------------------------------------------------------------

@app.get("/detections/by_date")
def get_detections_by_date(date: str, min_conf: float = 0.8):
    conn = get_db()
    rows = conn.execute(
        """SELECT scientific_name,
                  strftime('%H', timestamp) as hour,
                  confidence
           FROM detections
           WHERE DATE(timestamp) = ? AND confidence >= ?""",
        (date, min_conf)
    ).fetchall()
    conn.close()
    return [
        {
            "scientific_name": row["scientific_name"],
            "hour":            int(row["hour"]),
            "confidence":      row["confidence"],
        }
        for row in rows
    ]

# ----------------------------------------------------------------
# 3. Artsdetaljer: timestamp, recording, start/end_time, confidence
# ----------------------------------------------------------------
@app.get("/detections/species_details")
def get_species_details(
    date: str,
    scientific_name: str,
    hour: Optional[int] = None,
    min_conf: float = 0.0
):
    conn = get_db()
    if hour is not None:
        rows = conn.execute(
            """SELECT DISTINCT timestamp, recording, start_time, end_time, confidence
               FROM detections
               WHERE DATE(timestamp) = ? AND scientific_name = ?
               AND strftime('%H', timestamp) = ? AND confidence >= ?
               ORDER BY timestamp""",
            (date, scientific_name, f"{hour:02d}", min_conf)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT DISTINCT timestamp, recording, start_time, end_time, confidence
               FROM detections
               WHERE DATE(timestamp) = ? AND scientific_name = ? AND confidence >= ?
               ORDER BY timestamp""",
            (date, scientific_name, min_conf)
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ----------------------------------------------------------------
# 4. Admin artsliste: scientific_name + confidence for en dato
# ----------------------------------------------------------------
@app.get("/detections/species_list")
def get_species_list(date: str):
    conn = get_db()
    rows = conn.execute(
        "SELECT scientific_name, confidence FROM detections WHERE DATE(timestamp) = ?",
        (date,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ----------------------------------------------------------------
# 4. Admin artsliste: scientific_name + confidence for en dato
# ----------------------------------------------------------------
@app.get("/detections/species_list_singles")
def get_species_list(date: str):
    conn = get_db()
    rows = conn.execute(
        "SELECT DISTINCT scientific_name FROM detections WHERE DATE(timestamp) = ?",
        (date,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ----------------------------------------------------------------
# 5. Admin deteksjonsliste: alle felt for art + dato
# ----------------------------------------------------------------
@app.get("/detections/admin")
def get_detections_admin(date: str, scientific_name: str):
    conn = get_db()
    rows = conn.execute(
        """SELECT id, location_id, timestamp, scientific_name, confidence, recording, start_time, end_time
           FROM detections WHERE DATE(timestamp) = ? AND scientific_name = ?
           ORDER BY confidence DESC""",
        (date, scientific_name)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ----------------------------------------------------------------
# 6. Bekreftelsesdialog: hent detaljer for liste av IDer
# ----------------------------------------------------------------
@app.get("/detections/by_ids")
def get_detections_by_ids(ids: list[int] = Query(...)):
    conn = get_db()
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
#        f"SELECT id, timestamp, start_time, confidence FROM detections WHERE id IN ({placeholders})",
        f"SELECT id, timestamp, start_time, confidence FROM detections WHERE id IN ({placeholders}) ORDER BY confidence DESC",
        ids
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ----------------------------------------------------------------
# 7. Arkiver hel art for en dato → false_positives
# ----------------------------------------------------------------
@app.post("/detections/archive_species")
def archive_species(date: str, scientific_name: str):
    conn = get_db()
    conn.execute(
        """INSERT INTO false_positives (id, location_id, timestamp, scientific_name, confidence, recording, start_time, end_time)
           SELECT id, location_id, timestamp, scientific_name, confidence, recording, start_time, end_time
           FROM detections WHERE DATE(timestamp) = ? AND scientific_name = ?""",
        (date, scientific_name)
    )
    affected = conn.execute(
        "DELETE FROM detections WHERE DATE(timestamp) = ? AND scientific_name = ?",
        (date, scientific_name)
    ).rowcount
    conn.commit()
    conn.close()
    return {"archived": affected}

# ----------------------------------------------------------------
# 8. Arkiver enkeltdeteksjoner etter ID → false_positives
# ----------------------------------------------------------------
@app.post("/detections/archive_by_ids")
def archive_by_ids(ids: list[int]):
    conn = get_db()
    archived = 0
    for detection_id in ids:
        conn.execute(
            """INSERT INTO false_positives (id, location_id, timestamp, scientific_name, confidence, recording, start_time, end_time)
               SELECT id, location_id, timestamp, scientific_name, confidence, recording, start_time, end_time
               FROM detections WHERE id = ?""",
            (detection_id,)
        )
        conn.execute("DELETE FROM detections WHERE id = ?", (detection_id,))
        archived += 1
    conn.commit()
    conn.close()
    return {"archived": archived}

##################################################################
#  GRAFANA-SPESIFIKE QUERIES
##################################################################

# ----------------------------------------------------------------
# Filterkonfigurasjon
# ----------------------------------------------------------------
FILTER_DIR = "/home/e33admin/apps/BirdMicAnalyser/kilder"
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


# ----------------------------------------------------------------
# 9. Matrise: antall deteksjoner per art per time (pivotert)
#    Aggregerer over flere dager (from_date til to_date).
#    Filtrerer basert på filtertabell og overstyring.
# ----------------------------------------------------------------
@app.get("/detections/matrix")
def get_detections_matrix(
    from_date: str,
    to_date: str,
    min_conf: float = 0.8
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
    min_conf: float = 0.8
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
    min_conf: float = 0.8
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
    min_conf: float = 0.7
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
# ----------------------------------------------------------------
@app.get("/detections/recordings")
def get_recordings(
    from_date: str,
    to_date: str,
    scientific_name: str,
    min_conf: float = 0.7
):

    conn = get_db()
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
    min_conf: float = 0.7
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
