#!/bin/bash

# Sjekk tilgang til kildedatabase
SOURCE_DB="/home/e33admin/BirdEar-analyser/data/birdmic_detections.prod.sqlite"
BACKUP_DIR="/mnt/nas-e33_felles/birdmic/backup/data"

if [ ! -r "$SOURCE_DB" ]; then
    echo "FEIL: Ingen lesetilgang til $SOURCE_DB"
    exit 1
fi

if [ ! -d "$BACKUP_DIR" ] || [ ! -w "$BACKUP_DIR" ]; then
    echo "FEIL: Ingen skrivetilgang til $BACKUP_DIR"
    exit 1
fi

# Opprett backup
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/birdmic_detections.prod_${TIMESTAMP}.sqlite"

sqlite3 "$SOURCE_DB" ".backup '${BACKUP_FILE}'"

if [ ! -f "$BACKUP_FILE" ] || [ ! -s "$BACKUP_FILE" ]; then
    echo "FEIL: Backup mislyktes!"
    exit 1
fi

# Vent på at CIFS-cachen synkroniserer
sleep 5

# Integrity check
INTEGRITY=$(sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;")
if [ "$INTEGRITY" = "ok" ]; then
    echo "Backup OK: $BACKUP_FILE"
else
    echo "FEIL: Integrity check feilet!"
    echo "$INTEGRITY"
    rm "$BACKUP_FILE"
    exit 1
fi

# Slett backuper eldre enn 14 dager
find "$BACKUP_DIR" -name "birdmic_detections.prod_*.sqlite" -mtime +14 -delete
