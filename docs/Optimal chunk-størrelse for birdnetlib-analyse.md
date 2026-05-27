<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" class="logo" width="120"/>

## Optimal chunk-størrelse for birdnetlib-analyse

BirdNET (og dermed birdnetlib) er optimalisert for analyse av korte lydsegmenter, typisk mellom 10 og 15 sekunder per chunk. Dette er også anbefalt i relaterte prosjekter som BirdNET-Pi, hvor brukere ofte setter "record length" til 15 sekunder og "extract length" til 14 sekunder[^1]. Dette gir en god balanse mellom deteksjonskvalitet og prosesseringseffektivitet. For små chunk-størrelser (<10 sekunder) kan du risikere å miste deler av fuglelyder, mens for store chunk-størrelser (>20 sekunder) kan analysen bli tregere og mer ressurskrevende uten å gi bedre resultater.

**Anbefaling:**
Sett chunk-størrelsen til 14–15 sekunder for effektiv og nøyaktig analyse med birdnetlib.

## Filtrering og avstand mellom registreringer

For å minimere lagring og unngå duplikate registreringer av samme art, er det vanlig praksis å sette en minimumsavstand i tid mellom registreringer av samme art. BirdNET-Pi og lignende systemer bruker ofte 5–10 sekunder som terskel for å skille to registreringer av samme art, basert på at fuglelyder ofte varer noen sekunder og kan overlappe i tid[^1]. Dette betyr at hvis to deteksjoner av samme art er nærmere hverandre enn denne terskelen, bør de slås sammen til én registrering.

**Anbefaling:**
Bruk en minimumsavstand på 5–10 sekunder mellom registreringer av samme art for å regne dem som separate hendelser.

## Overlapp mellom chunkene

Overlapp mellom chunkene er viktig for å sikre at fuglelyder som starter i slutten av én chunk og fortsetter inn i neste ikke blir oversett. En typisk overlapp er 1 sekund mindre enn chunk-størrelsen, f.eks. 15 sekunders chunk med 14 sekunders "extract length" gir 1 sekund overlapp[^1]. Dette fanger opp lyder som krysser chunk-grensene uten å gi for mye overlapp og dobbelttelling.

**Anbefaling:**
Ha 1 sekund overlapp mellom chunkene, altså at hver nye chunk starter 14 sekunder etter forrige chunkstart hvis chunkene er 15 sekunder lange.

## Hvordan dele opp RTSP-strømmen for overlappende chunker

For å dele opp RTSP-strømmen i overlappende chunker kan du bruke ffmpeg slik:

```bash
ffmpeg -rtsp_transport tcp -i "rtsp://stream-url" -f segment -segment_time 15 -segment_overlap 1 -c copy chunk_%03d.wav
```

(OBS: `-segment_overlap` er ikke en standard ffmpeg-parameter, så du må i praksis bruke et skript som starter en ny segmentering hvert 14. sekund og lar segmentene overlappe med 1 sekund.)

Alternativt kan du i Python bruke en timer som starter en ny ffmpeg-prosess hvert 14. sekund og lar hver prosess ta opp 15 sekunder, slik at du får overlapp.

---

**Oppsummert:**

- Chunk-størrelse: 14–15 sekunder
- Overlapp: 1 sekund
- Minimumsavstand mellom registreringer av samme art: 5–10 sekunder
- Del opp RTSP-strømmen med overlappende segmenter, enten via ffmpeg eller skriptstyrt segmentering[^1].

Dette gir optimal ytelse og nøyaktighet for birdnetlib-analyse av RTSP-strømmer.

<div style="text-align: center">⁂</div>

[^1]: https://github.com/Nachtzuster/BirdNET-Pi/discussions/189

[^2]: https://github.com/mcguirepr89/BirdNET-Pi/discussions/251

[^3]: https://forum.knime.com/t/chunk-size-for-streaming/10285

[^4]: https://forum.image.sc/t/deciding-on-optimal-chunk-size/63023/3

[^5]: https://www.youtube.com/watch?v=8bp1IH11msI

[^6]: https://github.com/joeweiss/birdnetlib/blob/main/README.md

[^7]: https://github.com/joeweiss/birdnetlib/issues

0
