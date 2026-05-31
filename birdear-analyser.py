import sqlite3
import yaml
from datetime import datetime
from birdnetlib import Recording
from birdnetlib.analyzer import Analyzer
from pydub import AudioSegment
import os
import shutil
import sys
import re
import logging
from datetime import datetime
import time

def configure_logging(logging_enabled):
    """
    Konfigurerer logging basert på parameteren logging_enabled.
    """
    if logging_enabled:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.StreamHandler()]
        )
        logging.getLogger('birdnetlib').setLevel(logging.INFO) # Reduser Librosa-loggingimport librosa
        logging.getLogger('librosa').setLevel(logging.INFO) # Reduser Librosa-loggingimport librosa
        logging.getLogger('pydub').setLevel(logging.INFO) # Reduser Librosa-loggingimport librosa
    else:
        logging.basicConfig(
            level=logging.CRITICAL  # Undertrykker alle meldinger unntatt kritiske feil
        )
        logging.getLogger('birdnetlib').setLevel(logging.CRITICAL) # Reduser Librosa-loggingimport librosa
        logging.getLogger('librosa').setLevel(logging.CRITICAL) # Reduser Librosa-loggingimport librosa
        logging.getLogger('pydub').setLevel(logging.CRITICAL) # Reduser Librosa-loggingimport librosa

def load_config(config_path='config.yaml'):
    """
    Leser inn konfigurasjonsfilen fra den angitte stien.
    """
    if not os.path.exists(config_path):
        print(f"Konfigurasjonsfilen {config_path} finnes ikke.")
        sys.exit(1)

    with open(config_path, 'r') as file:
        return yaml.safe_load(file)

class DatabaseHandler:
    """
    Klasse for å håndtere databaseoperasjoner.
    """
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """
        Initialiserer databasen og oppretter nødvendige tabeller hvis de ikke finnes.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        conn.execute("PRAGMA journal_mode=WAL")  # For bedre ytelse ved samtidige tilkoblinger

        # Opprett detections-tabellen med oppdatert struktur
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY,
            location_id TEXT,
            scientific_name TEXT,
            start_time REAL,
            end_time REAL,
            confidence REAL,
            recording TEXT,
            timestamp TEXT
        )
        ''')

        # Opprett locations-tabellen
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            name TEXT NOT NULL,
            description TEXT
        )
        ''')

        conn.commit()
        conn.close()

    def get_or_create_location(self, location):
        """
        Henter eller oppretter en lokasjon i databasen.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
        SELECT id FROM locations WHERE lat = ? AND lon = ? AND name = ?
        ''', (location['lat'], location['lon'], location['name']))
        result = cursor.fetchone()

        if result:
            location_id = result[0]
        else:
            cursor.execute('''
            INSERT INTO locations (lat, lon, name, description)
            VALUES (?, ?, ?, ?)
            ''', (location['lat'], location['lon'], location['name'], location.get('description', '')))
            conn.commit()
            location_id = cursor.lastrowid

        conn.close()
        return location_id

    def save_detections(self, detections, recording, location_id, timestamp):
        """
        Lagrer deteksjoner fra en lydfil i databasen.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        for detection in detections:
            cursor.execute('''
            INSERT INTO detections (
                location_id, scientific_name, start_time, end_time, confidence, recording, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                location_id,
                detection['scientific_name'],
                detection['start_time'],  # start_time i sekunder
                detection['end_time'],    # end_time i sekunder
                detection['confidence'],
                recording,  # Filnavnet som recording
                timestamp.isoformat()  # Tidsstempelet fra filnavnet
            ))

        conn.commit()
        conn.close()

# Sjekk eller opprett lokasjon
def get_or_create_location(db_path, location):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT id FROM locations WHERE lat = ? AND lon = ? AND name = ?
    ''', (location['lat'], location['lon'], location['name']))
    result = cursor.fetchone()
    
    if result:
        location_id = result[0]
    else:
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            length REAL NOT NULL,
            scientific_name TEXT NOT NULL,
            common_name TEXT NOT NULL,
            confidence REAL NOT NULL,
            chunk_index TEXT NOT NULL,
            location_id INTEGER NOT NULL,
            FOREIGN KEY (location_id) REFERENCES locations (id)
        )
        ''')

        # Opprett locations-tabellen
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            name TEXT NOT NULL,
            description TEXT
        )
        ''')

        conn.commit()
        location_id = cursor.lastrowid
    
    conn.close()
    return location_id

# Lagring av deteksjoner
def save_detections(recording, db_path, file_name, location_id):
    """
    Lagrer deteksjoner fra en lydfil i databasen.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    for detection in recording.detections:
        cursor.execute('''
        SELECT id FROM locations WHERE lat = ? AND lon = ? 
        ''', (location['lat'], location['lon']))
        result = cursor.fetchone()

        if result:
            location_id = result[0]
        else:
            cursor.execute('''
            INSERT INTO locations (lat, lon, name, description)
            VALUES (?, ?, ?, ?)
            ''', (location['lat'], location['lon'], location['name'], location.get('description', '')))
            conn.commit()
            location_id = cursor.lastrowid

        conn.close()
        return location_id

class AudioProcessor:
    """
    Klasse for å håndtere forhåndsprosessering og analyse av lydfiler.
    """
    def __init__(self, birdnet_analyzer, min_conf, lat, lon, normalize=False, highpass_filter=False, highpass_cutoff=0):
        self.birdnet_analyzer = birdnet_analyzer
        self.min_conf = min_conf
        self.lat = lat
        self.lon = lon
        self.normalize = normalize
        self.highpass_filter = highpass_filter
        self.highpass_cutoff = highpass_cutoff
        self.temp_file_path = None

    def __cleanup_temp_file(self):
        """
        Fjerner den midlertidige filen.
        """
        if self.temp_file_path and os.path.exists(self.temp_file_path):
            logging.info(f"Fjerner midlertidig fil: {self.temp_file_path}")
            os.remove(self.temp_file_path)
            self.temp_file_path = None

    def analyze(self, file_path, chunk_length, overlap, file_creation_time):
        """
        Deler opp lydfilen i mindre chunks og analyserer hver chunk.
        """
        logging.info(f"Deler opp filen {file_path} i chunks med lengde {chunk_length} ms og overlap {overlap} ms...")

        # Last inn lydfilen
        audio = AudioSegment.from_file(file_path, format="wav")
        file_duration = len(audio)  # Total varighet i millisekunder

        detections = []
        start = 0

        while start < file_duration:
            end = min(start + chunk_length, file_duration)
            chunk = audio[start:end]

            # Normalisering
            if self.normalize:
                logging.info(f"Normaliserer chunk fra {start} ms til {end} ms...")
                chunk = chunk.normalize()

            # Høypassfiltrering
            if self.highpass_filter:
                logging.info(f"Bruker høypassfilter på chunk fra {start} ms til {end} ms...")
                chunk = chunk.high_pass_filter(self.highpass_cutoff)

            # Eksporter chunk til en midlertidig fil
            self.temp_file_path = f"{file_path}.chunk_{start}_{end}.temp.wav"
            chunk.export(self.temp_file_path, format="wav")

            # Utfør analysen
            recording = Recording(
                self.birdnet_analyzer,
                self.temp_file_path,
                date=file_creation_time,  # Bruk tidsstempelet fra filnavnet
                min_conf=self.min_conf,
                lat=self.lat,
                lon=self.lon
            )
            recording.analyze()

            # Legg til deteksjoner fra denne chunken
            detections.extend(recording.detections)

            # Fjern midlertidig fil
            self.__cleanup_temp_file()

            # Flytt startpunktet med (chunk_length - overlap)
            start += chunk_length - overlap

        return detections

    def process_file(self, file_path, chunk_length, overlap, file_creation_time):
        """
        Utfører forhåndsprosessering og analyse på en lydfil.
        Hvis filen er lengre enn chunk_length, deles den opp i chunks.
        """
        audio = AudioSegment.from_file(file_path, format="wav")
        if len(audio) > chunk_length:
            logging.info(f"Filen {file_path} er lengre enn {chunk_length} ms. Behandler i chunks...")
            return self.analyze(file_path, chunk_length, overlap, file_creation_time)
        else:
            logging.info(f"Filen {file_path} er kortere enn {chunk_length} ms. Behandler hele filen...")
            return self.analyze(file_path, len(audio), 0, file_creation_time)  # Ingen overlapping for korte filer

def extract_file_creation_time(file_name):
    """
    Ekstraherer tidsstempelet fra filnavnet og returnerer det som en datetime-objekt.
    Forventet format på filnavnet: "[valgfritt_prefiks]_[timestamp:format=yyyymmdd-hhmmss].wav"
    """
    match = re.search(r"(\d{8}-\d{6})\.wav$", file_name)
    if match:
        timestamp_str = match.group(1)  # Eksempel: "20230428-153045"
        return datetime.strptime(timestamp_str, "%Y%m%d-%H%M%S")
    else:
        raise ValueError(f"Ugyldig filnavnformat: {file_name}")

# Prosessering av lydfiler
def process_audio_files(config):
    """
    Prosesserer lydfiler fra en angitt sti, analyserer dem med BirdNET-lib,
    og håndterer flytting/sletting basert på registreringer.
    """
    db_path = config["db-path"]
    audio_path = config["audio-path"]
    audio_archive_path = config["audio-archive-path"]
    location = config["location"]
    wait_period = config["analyse"]["wait_periode_for_audio_files"]

    # Hent streamchunks-parametere
    chunk_length = config["streamchunks"]["chunk_length"]
    overlap = config["streamchunks"]["overlap"]

    # Initialiser database og lokasjon
    db_handler = DatabaseHandler(db_path)
    location_id = db_handler.get_or_create_location(location)

    # Opprett en instans av AudioProcessor
    audio_processor = AudioProcessor(
        birdnet_analyzer=Analyzer(),
        min_conf=config["analyse"]["min_confidence"],
        lat=location["lat"],
        lon=location["lon"],
        normalize=config["preprocessing"]["normalize"],
        highpass_filter=config["preprocessing"]["highpass_filter"],
        highpass_cutoff=config["preprocessing"]["highpass_cutoff"]
    )

    while True:
        # Hent alle lydfiler i audio-path
        files = [f for f in os.listdir(audio_path) if f.endswith(".wav")]

        if not files:
            print(f"Ingen lydfiler funnet i {audio_path}. Venter i {wait_period} sekunder...")
            time.sleep(wait_period)
            continue

        # Prosesser hver lydfil
        for file in sorted(files):
            file_path = os.path.join(audio_path, file)
            print(f"Prosesserer {file_path}...")

            # Hent tidspunktet for når filen ble opprettet
            file_creation_time = extract_file_creation_time(file)
            print(f"Fil opprettet: {file_creation_time.isoformat()}")

            # Utfør forhåndsprosessering og analyse
            detections = audio_processor.process_file(file_path, chunk_length, overlap, file_creation_time)

            # Hvis deteksjoner finnes, lagre dem i databasen og eksporter til MP3 før flytting
            if detections:
                # Eksporter den forhåndsproesserte lyden til MP3
                mp3_file_path = os.path.join(audio_archive_path, f"{os.path.splitext(file)[0]}.mp3")
                print(f"Eksporterer {file_path} til MP3: {mp3_file_path}...")
                audio = AudioSegment.from_file(file_path, format="wav")
                audio.export(mp3_file_path, format="mp3", bitrate="320k")

                # Lagre deteksjoner i databasen med MP3-filen som recording
                db_handler.save_detections(detections, os.path.basename(mp3_file_path), location_id, file_creation_time)

                # Flytt original WAV-fil til arkivet
                archive_path = os.path.join(audio_archive_path, file)
                print(f"Flytter {file_path} til {archive_path}...")
                shutil.move(file_path, archive_path)

                # Slett WAV-filen etter at MP3-filen er opprettet
                if os.path.exists(archive_path):
                    print(f"Sletter WAV-fil: {archive_path}")
                    os.remove(archive_path)
            else:
                print(f"Sletter {file_path} (ingen registreringer)...")
                os.remove(file_path)

if __name__ == '__main__':
    # Sjekk om en konfigurasjonsfil er spesifisert som argument
    if len(sys.argv) == 2:
        config_path = sys.argv[1]
        print(f"Laster konfigurasjonsfil fra: {config_path}")
    else:
        # Bruk standard konfigurasjonsfil hvis ingen argumenter er gitt
        config_path = "config-default.yaml"
        print(f"Ingen konfigurasjonsfil spesifisert. Bruker standard: {config_path}")

    # Last inn konfigurasjonen
    config = load_config(config_path)

    # Prosesser lydfiler
    process_audio_files(config)

