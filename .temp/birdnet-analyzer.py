import os
from birdnetlib import Recording
from birdnetlib.analyzer import Analyzer

# Sti til mappen med lydfiler
audio_folder_path = "/mnt/e33nas_felles/birdmic/analyser-TEST"

locale = "nb_NO"
lat = 63.3724
lon = 10.3975


# Initialiser Analyzer
Analyzer(locale="nb_NO", lat=lat, lon=lon)
#analyzer = Analyzer()

# Iterer gjennom alle .wav-filer i mappen
for file_name in sorted(os.listdir(audio_folder_path)):
    if file_name.endswith(".wav"):
        audio_file_path = os.path.join(audio_folder_path, file_name)
        print(f"**********\nAnalyserer fil: {audio_file_path}")

        # Analyser lydfilen
        recording = Recording(
            analyzer,
            audio_file_path,
            date=None,  # Du kan spesifisere en dato hvis ønskelig
            min_conf=0.5  # Minimum konfidensverdi for deteksjoner
        )

        recording.analyze()

        # Skriv ut analyseresultatene
        if recording.detections:
            print("Analyseresultater:")
            for detection in recording.detections:
                print(f"Art: {detection['common_name']} ({detection['scientific_name']})")
                print(f"Starttid: {detection['start_time']} sekunder")
                print(f"Sluttid: {detection['end_time']} sekunder")
                print(f"Konfidens: {detection['confidence']}")
                print("-" * 40)
        else:
            print("Ingen deteksjoner funnet.")
        print("\n")

