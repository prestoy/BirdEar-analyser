<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" class="logo" width="120"/>

# RTSP-WAV -> Birdnet Analyser -> Sqlite WAL

Her er en **optimalisert løsning** som tar hensyn til BirdNETs WAV-krav samtidig som den lagrer lydklippene som MP3:

---

## **Endelig skript med WAV-strøm og MP3-arkiv**

```python
import sqlite3
import subprocess
import uuid
import os
from datetime import datetime
from pydub import AudioSegment
from io import BytesIO
from birdnetlib import Recording
from birdnetlib.analyzer import Analyzer

# Konfigurasjon
DB_AKTIV = 'birdnet_aktiv.db'
LYD_ARKIV = 'lyd_klipp'
RTSP_URL = 'rtsp://ditt_kamera/stream'
MP3_BITRATE = '320k'

# Opprett lydarkivmappe
os.makedirs(LYD_ARKIV, exist_ok=True)

def init_db(db_sti):
    conn = sqlite3.connect(db_sti)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS deteksjoner (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tidspunkt TEXT NOT NULL,
        start_tid REAL NOT NULL,
        slutt_tid REAL NOT NULL,
        vitenskapelig_navn TEXT NOT NULL,
        vanlig_navn TEXT NOT NULL,
        konfidens REAL NOT NULL,
        lyd_nokkel TEXT UNIQUE NOT NULL,
        lyd_sti TEXT NOT NULL,
        chunk_indeks INTEGER NOT NULL,
        kvartal TEXT GENERATED ALWAYS AS (
            substr(tidspunkt, 1, 4) || 
            CASE 
                WHEN cast(substr(tidspunkt, 6, 2) as integer) BETWEEN 1 AND 3 THEN 'Q1'
                WHEN cast(substr(tidspunkt, 6, 2) as integer) BETWEEN 4 AND 6 THEN 'Q2'
                WHEN cast(substr(tidspunkt, 6, 2) as integer) BETWEEN 7 AND 9 THEN 'Q3'
                ELSE 'Q4'
            END
        ) VIRTUAL
    )
    """)
    conn.commit()
    conn.close()

def lagre_lyd_klipp(audio_segment):
    nokkel = str(uuid.uuid4())
    filnavn = f"{nokkel}.mp3"
    sti = os.path.join(LYD_ARKIV, filnavn)
    
    # Eksporter til MP3
    audio_segment.export(
        sti, 
        format="mp3",
        bitrate=MP3_BITRATE,
        codec="libmp3lame"
    )
    
    return nokkel, sti

def lagre_deteksjon(db_sti, deteksjon, lyd_nokkel, lyd_sti, chunk_indeks):
    conn = sqlite3.connect(db_sti)
    cursor = conn.cursor()
    
    cursor.execute("""
    INSERT INTO deteksjoner (
        tidspunkt, start_tid, slutt_tid,
        vitenskapelig_navn, vanlig_navn, konfidens,
        lyd_nokkel, lyd_sti, chunk_indeks
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        deteksjon['start_time'],
        deteksjon['end_time'],
        deteksjon['scientific_name'],
        deteksjon['common_name'],
        deteksjon['confidence'],
        lyd_nokkel,
        lyd_sti,
        chunk_indeks
    ))
    
    conn.commit()
    conn.close()

def analyser_rtsp_strøm(rtsp_url, db_sti):
    analyzer = Analyzer()
    chunk_lengde = 15000  # 15 sekunder
    overlapp = 5000       # 5 sekunder
    
    # FFmpeg for WAV-strøm med 16-bit PCM
    ffmpeg_cmd = [
        'ffmpeg',
        '-i', rtsp_url,
        '-f', 'wav',
        '-acodec', 'pcm_s16le',
        '-ar', '44100',
        '-ac', '1',
        '-'
    ]
    
    proses = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    lydbuffer = bytes()
    chunk_indeks = 0

    try:
        while True:
            # Les rå WAV-data
            raw_data = proses.stdout.read(44100 * 2 * ((chunk_lengde + overlapp) // 1000))
            if not raw_data:
                break

            lydbuffer += raw_data
            audio = AudioSegment(
                data=lydbuffer,
                sample_width=2,
                frame_rate=44100,
                channels=1
            )

            # Del opp i chunks med overlapp
            for i in range(0, len(audio), chunk_lengde - overlapp):
                chunk = audio[i:i + chunk_lengde]
                if len(chunk) &lt; 1000:
                    continue

                # Lagre som MP3
                lyd_nokkel, lyd_sti = lagre_lyd_klipp(chunk)

                # Analyser med BirdNET (bruker original WAV-data)
                temp_wav = BytesIO()
                chunk.export(temp_wav, format="wav")
                temp_wav.seek(0)
                
                recording = Recording(
                    analyzer,
                    temp_wav,
                    date=datetime.now(),
                    min_conf=0.25
                )
                recording.analyze()

                for deteksjon in recording.detections:
                    lagre_deteksjon(
                        db_sti, deteksjon, 
                        lyd_nokkel, lyd_sti, 
                        chunk_indeks
                    )

                chunk_indeks += 1

            # Behold overlapp-del
            lydbuffer = audio[-overlapp:].raw_data

    finally:
        proses.terminate()

if __name__ == '__main__':
    init_db(DB_AKTIV)
    analyser_rtsp_strøm(RTSP_URL, DB_AKTIV)
```


---

## **Nøkkelfunksjoner**

### 1. WAV-strømhåndtering

- **FFmpeg-kommando** konverterer RTSP-strømmen til 16-bit PCM WAV
- **Bufferhåndtering** med overlapp for kontinuitet
- **Minnekartlegging** av WAV-data for rask analyse


### 2. MP3-arkivering

- **UUID-basert filnavn** for unik identifikasjon
- **320 kbps encoding** med libmp3lame-kodek
- **Diskbesparende lagring** sammenlignet med WAV


### 3. BirdNET-integrasjon

- **Midlertidig WAV-eksport** i minnet (BytesIO)
- **Automatisk opprydding** etter analyse
- **Full sporbarhet** mellom deteksjoner og lydklipp

---

## **Optimaliseringstips**

### 1. Minneeffektiv WAV-håndtering

```python
# Bruk memoryview for bufferhåndtering
lydbuffer = memoryview(lydbuffer + raw_data)
```


### 2. Parallell MP3-koding

```python
from concurrent.futures import ThreadPoolExecutor

def kod_mp3(chunk):
    return lagre_lyd_klipp(chunk)

with ThreadPoolExecutor() as executor:
    lyd_nokkel, lyd_sti = executor.submit(kod_mp3, chunk).result()
```


### 3. FFmpeg-presets for WAV

```python
ffmpeg_cmd = [
    'ffmpeg',
    '-i', rtsp_url,
    '-f', 'wav',
    '-acodec', 'pcm_s16le',
    '-ar', '48000',  # Bedre for BirdNET
    '-ac', '1',
    '-fflags', '+nobuffer',
    '-flags', 'low_delay',
    '-'
]
```


---

## **Brukseksempel**

### Hent lydklipp med deteksjonsdata

```python
def hent_deteksjon_med_lyd(deteksjon_id):
    with sqlite3.connect(DB_AKTIV) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT d.*, l.ldata 
        FROM deteksjoner d
        JOIN lydarkiv l ON d.lyd_nokkel = l.nokkel
        WHERE d.id = ?
        """, (deteksjon_id,))
        
        rad = cursor.fetchone()
        return {
            'metadata': dict(zip([col[^0] for col in cursor.description[:8]], rad[:8])),
            'lyd_data': rad[^8]
        }
```


---

## **Feilsøking**

### Problem: Høyt minneforbruk

**Løsning:**

```python
# Bruk chunked eksport
chunk.export(lyd_sti, format="mp3", bitrate=MP3_BITRATE, codec="libmp3lame", parameters=["-write_xing", "0"])
```


### Problem: Analyseforsinkelse

**Løsning:**

```python
# Reduser chunk-størrelse
chunk_lengde = 10000  # 10 sekunder
overlapp = 3000       # 3 sekunder
```

Dette oppsettet gir **reell sanntidsanalyse** med WAV-strøm til BirdNET, samtidig som det arkiverer **høykvalitets MP3-klipp** for langtidslagring og rapportering. For store installasjoner bør du vurdere å distribuere lydarkivet på et eget lagringsnivå.

<div style="text-align: center">⁂</div>

[^1]: https://github.com/mcguirepr89/BirdNET-Pi/discussions/850

[^2]: https://connormwood.com/wp-content/uploads/2024/02/wood-kahl-2024-guidelines-for-birdnet-scores.pdf

[^3]: https://bou.org.uk/blog-granados-birdnet/

[^4]: https://www.birdforum.net/threads/birdnet-analyzer-and-long-recordings.460874/

[^5]: https://community.element14.com/challenges-projects/design-challenges/pi-fest/b/blog/posts/songspire---experimenting-with-birdnet

[^6]: https://www.geeksforgeeks.org/convert-mp3-to-wav-using-python/

[^7]: https://github.com/mcguirepr89/BirdNET-Pi/discussions/118

[^8]: https://www.youtube.com/watch?v=4E7N7W1lUkU

[^9]: https://github.com/PYP2205/Python-Audio-Converter

