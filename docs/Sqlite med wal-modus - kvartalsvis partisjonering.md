<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" class="logo" width="120"/>

# Sqlite med wal-modus og kvartalsvis partisjonering

Her er en **komplett løsning** for SQLite med WAL-modus og kvartalsvis datahåndtering:

---

## 1. **Databaseoppsett med partisjonering**

### A. **Aktivér WAL-modus**


```python

import sqlite3

def opprett_database(db_sti):
    conn = sqlite3.connect(db_sti)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS deteksjoner (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tidspunkt TEXT NOT NULL,
        art TEXT NOT NULL,
        konfidens REAL NOT NULL,
        lydsti TEXT NOT NULL,
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
```


### B. **Optimaliseringsindekser**

```python
conn.execute("CREATE INDEX IF NOT EXISTS idx_kvartal ON deteksjoner(kvartal)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_tidspunkt ON deteksjoner(tidspunkt)")
```


---

## 2. **Automatisk eksport av gamle data**

### A. **Eksportskript**

```python
def eksporter_kvartal(kilde_db, mål_db, kvartal):
    with sqlite3.connect(kilde_db) as kilde, sqlite3.connect(mål_db) as mål:
        kilde_cursor = kilde.cursor()
        mål_cursor = mål.cursor()
        
        # Kopier data
        kilde_cursor.execute("""
        ATTACH DATABASE ? AS arkiv
        """, (mål_db,))
        
        kilde_cursor.execute("""
        INSERT INTO arkiv.deteksjoner 
        SELECT * FROM main.deteksjoner 
        WHERE kvartal = ?
        """, (kvartal,))
        
        # Slett eksporterte data
        kilde_cursor.execute("""
        DELETE FROM main.deteksjoner 
        WHERE kvartal = ?
        """, (kvartal,))
        
        kilde.commit()
```


### B. **Planlagt vedlikehold**

```python
import schedule
import time

def kvartalsvis_vedlikehold():
    nåværende_kvartal = ... # Kalkuler gjeldende kvartal
    eldre_kvartal = ... # Kalkuler forrige kvartal
    
    eksporter_kvartal(
        "aktiv.db", 
        f"arkiv_{eldre_kvartal}.db",
        eldre_kvartal
    )
    
    # Komprimer database
    with sqlite3.connect("aktiv.db") as conn:
        conn.execute("VACUUM")

# Kjør daglig kl 03:00
schedule.every().day.at("03:00").do(kvartalsvis_vedlikehold)

while True:
    schedule.run_pending()
    time.sleep(60)
```


---

## 3. **Rapporteringssystem**

### A. **Kombinerte rapporter**

```python
def generer_rapport(start_kvartal, slutt_kvartal):
    rapporter = []
    
    for kvartal in kvartaler_i_periode(start_kvartal, slutt_kvartal):
        with sqlite3.connect(f"arkiv_{kvartal}.db") as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT art, COUNT(*) as antall
            FROM deteksjoner
            GROUP BY art
            ORDER BY antall DESC
            """)
            rapporter.extend(cursor.fetchall())
    
    return rapporter
```


### B. **Tidsreise-analyse**

```python
def sammenlign_kvartaler(kvartal1, kvartal2):
    with sqlite3.connect(f"arkiv_{kvartal1}.db") as conn1, \
         sqlite3.connect(f"arkiv_{kvartal2}.db") as conn2:
        
        cursor1 = conn1.cursor()
        cursor1.execute("""
        SELECT art, COUNT(*) 
        FROM deteksjoner 
        GROUP BY art
        """)
        data1 = dict(cursor1.fetchall())
        
        cursor2 = conn2.cursor()
        cursor2.execute("""
        SELECT art, COUNT(*) 
        FROM deteksjoner 
        GROUP BY art
        """)
        data2 = dict(cursor2.fetchall())
        
        return {
            "endringer": {
                art: data2.get(art, 0) - data1.get(art, 0)
                for art in set(data1) | set(data2)
            },
            "vekst": (sum(data2.values()) - sum(data1.values())) / sum(data1.values()) * 100
        }
```


---

## 4. **Fysisk databasestruktur**

```
birdnet/
├── aktiv.db       # Nåværende kvartal (WAL-modus)
├── aktiv.db-wal   # WAL-fil
├── arkiv/
│   ├── 2023Q1.db
│   ├── 2023Q2.db
│   └── 2023Q3.db
└── rapporter/
    ├── artsmønster.pdf
    └── sesongvariasjoner.csv
```


---

## 5. **Ytelsesoptimalisering**

```python
# Bruk WAL checkpointing
conn.execute("PRAGMA wal_autocheckpoint=1000")  # Sjekkpunkt hver 1000 sider

# Aktiver minnetilpasset I/O
conn.execute("PRAGMA mmap_size=268435456")  # 256 MB minnekartlegging

# Optimaliser skrivebuffer
conn.execute("PRAGMA cache_size=-2000")  # 2 MB cache
```


---

## 6. **Feilhåndtering og Recovery**

```python
def verifiser_arkiv(kvartal):
    try:
        with sqlite3.connect(f"arkiv_{kvartal}.db") as conn:
            conn.execute("PRAGMA integrity_check")
            return True
    except sqlite3.DatabaseError as e:
        print(f"Feil i arkiv {kvartal}: {e}")
        return False

def gjenopprett_arkiv(kvartal):
    backup_sti = f"backup/arkiv_{kvartal}.db.bak"
    if os.path.exists(backup_sti):
        shutil.copy2(backup_sti, f"arkiv_{kvartal}.db")
        return verifiser_arkiv(kvartal)
    return False
```


---

## 7. **Brukseksempel**

```python
# Oppsett
opprett_database("aktiv.db")

# Innsetting av data
def lagre_deteksjon(art, konfidens, lydsti):
    with sqlite3.connect("aktiv.db") as conn:
        conn.execute("""
        INSERT INTO deteksjoner (tidspunkt, art, konfidens, lydsti)
        VALUES (datetime('now'), ?, ?, ?)
        """, (art, konfidens, lydsti))

# Kvartalsvis rapportering
def generer_kvartalsrapport(kvartal):
    with sqlite3.connect(f"arkiv_{kvartal}.db") as conn:
        resultat = conn.execute("""
        SELECT strftime('%Y-%m', tidspunkt) as måned, 
               art, 
               COUNT(*) as antall
        FROM deteksjoner
        GROUP BY måned, art
        ORDER BY måned, antall DESC
        """).fetchall()
    
    return pd.DataFrame(resultat, columns=["Måned", "Art", "Antall"])
```


---

Denne løsningen gir **høy ytelse** gjennom WAL-modus, **automatisk datahåndtering** ved kvartalsskifte, og **skalerbar rapportering** på arkiverte datasett. For store installasjoner kan du vurdere å distribuere arkivdatabasene på separate lagringsvolumer.

<div style="text-align: center">⁂</div>

[^1]: https://www.sqlite.org/wal.html

[^2]: https://www.sqlite.org/walformat.html

[^3]: https://sqlite.org/cgi/src/doc/wal2/doc/wal2.md

[^4]: https://stackoverflow.com/questions/14234007/sqlite-wal-mode-with-multiple-transactions-in-multiple-threads

[^5]: https://blog.sqlitecloud.io/journal-modes-in-sqlite

[^6]: https://www.sqlite.org/fileformat.html

[^7]: https://sqlite.org/forum/info/117c91891cf7ac15

[^8]: https://fly.io/blog/wal-mode-in-litefs/

[^9]: https://www.sqlite.org/datatype3.html

