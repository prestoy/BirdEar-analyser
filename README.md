# BirdMicAnalyser

BirdMicAnalyser er et Python-basert prosjekt for å analysere lydopptak av fugler. Prosjektet inkluderer en webserver bygget med FastAPI og Jinja2 for å vise deteksjoner av fugler basert på lydopptak lagret i en SQLite-database. Lydfilene analyseres og deteksjoner lagres automatisk fra en angitt mappe.

## Funksjonalitet

- **Automatisk lydanalyse**: Prosesserer og analyserer alle `.wav`-filer i en angitt mappe, lagrer deteksjoner i SQLite.
- **Kalenderoversikt**: Viser en månedskalender som markerer dager med fugledeteksjoner.
- **Detaljvisning**: Viser detaljerte registreringer for en valgt dato, inkludert histogrammer for antall registreringer per time.
- **Filtrering**: Brukeren kan angi et minimumskonfidensnivå for å filtrere registreringene.
- **Arkivering**: Lydfiler med deteksjoner konverteres til MP3 og arkiveres, original WAV slettes etterpå.
- **Støtte for flere lokasjoner**: Lokasjonsdata lagres og gjenbrukes i databasen.

## Teknologier

- **Backend**: FastAPI
- **Frontend**: Jinja2-templates
- **Database**: SQLite
- **Lydanalyse**: BirdNET-lib
- **Språk**: Python 3.12
- **Lydbehandling**: pydub

## Installasjon

1. **Klon prosjektet**:
    ```bash
    git clone https://github.com/brukernavn/BirdMicAnalyser.git
    cd BirdMicAnalyser
    ```

2. **Opprett et virtuelt miljø**
    ```bash
    python3 -m venv .env
    source .env/bin/activate
    ```

3. **Installer avhengigheter**
    ```bash
    pip install -r requirements.txt
    ```

4. **Konfigurer prosjektet**
    - Opprett en `config.yaml` eller bruk `config-default.yaml` som mal. Eksempel:
        ```yaml
        db-path: "birdmic_detections.db"
        audio-path: "lydfiler/"
        audio-archive-path: "arkiv/"
        location:
          lat: 59.9139
          lon: 10.7522
          name: "Oslo"
          description: "Sentrum"
        analyse:
          min_confidence: 0.7
          wait_periode_for_audio_files: 60
        streamchunks:
          chunk_length: 15000
          overlap: 5000
        preprocessing:
          normalize: true
          highpass_filter: false
          highpass_cutoff: 1000
        ```
    - Sørg for at nødvendige mapper som `lydfiler/` og `arkiv/` eksisterer.

## Bruk

- **Automatisk analyse**: Lydfiler som legges i mappen angitt som `audio-path` i konfigurasjonen (f.eks. `lydfiler/`), behandles fortløpende av `stream_analyser.py`. Nye `.wav`-filer analyseres automatisk, og deteksjoner lagres i databasen.
- **Arkivering**: Dersom det oppdages fugl i en fil, konverteres filen til MP3 og flyttes til arkivmappen (`audio-archive-path`). Original WAV-fil slettes etterpå.
- **Ingen deteksjon**: Filer uten deteksjoner slettes automatisk.
- **Konfigurasjon**: Parametre som minimum konfidens, chunk-lengde, overlapp og forhåndsprosessering settes i `config.yaml` eller `config-default.yaml`.
- **Oppstart**: Start analysen med:
    ```bash
    python stream_analyser.py config.yaml
    ```
    eller uten argument for å bruke `config-default.yaml`:
    ```bash
    python stream_analyser.py
    ```
- **Krav til filnavn**: Lydfilene må ha et navn på formatet `[valgfritt_prefiks]_<yyyymmdd-hhmmss>.wav` (f.eks. `birdmic_20240522-153045.wav`).

Se loggmeldinger i terminalen for status og eventuelle feil.

## Lisens
Dette prosjektet er lisensiert under MIT-lisensen. Se LICENSE-filen for mer informasjon.

## Bidrag
Bidrag er velkomne! Opprett en pull request eller kontakt prosjektets vedlikeholder for mer informasjon.

## Kontakt
For spørsmål eller tilbakemeldinger, kontakt stale@prestoy.no.
