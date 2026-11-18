# MarktVizier-datagenerator

Oefendata voor je e-commerce data warehouse op Google Cloud. De generator simuleert bijna twee jaar
(januari 2025 t/m november 2026) van de fictieve duurzame woonwebshop **MarktVizier** en maakt daar
zes bronnen van, in het formaat waarin de echte connectors ze aanleveren:

| Bron | Formaat | Speelt de rol van | Komt in BigQuery in |
|---|---|---|---|
| Webshopdatabase | NDJSON (orders, orderregels, klanten, producten) | Datastream vanuit Cloud SQL PostgreSQL | `raw_webshop` |
| GA4 | NDJSON per dag, echt exportschema (genest) | GA4 BigQuery-export | `analytics_123456789.events_JJJJMMDD` |
| Google Ads | NDJSON, DTS-tabelnamen en -kolommen | BigQuery Data Transfer Service | `raw_ads.ads_*_1234567890` |
| Meta Ads | CSV | DTS-connector Facebook Ads | `raw_ads.meta_ad_insights` |
| E-mailplatform | NDJSON met JSON-payload | Cloud Run job op de API | `raw_email.events` |
| Leveranciers | CSV (Noorderlicht wekelijks, Hout & Heem maandelijks) | upload in Cloud Storage | `raw.prijzen_noorderlicht`, `raw.prijzen_houtheem` |

Alle bronnen delen dezelfde werkelijkheid. Een order in de webshop heeft (meestal) een GA4-sessie met
dezelfde `transaction_id`, die sessie komt uit een campagne waarvan de kosten in Google Ads of Meta staan,
en de klant krijgt nieuwsbrieven op hetzelfde e-mailadres. Precies zoals bij een echte klant zit er ook
rommel in: dubbele klanten, rare codes, verschillende tijdzones en eenheden. Zo heeft je zilverlaag echt
iets te doen.

**Omvang bij standaardinstellingen:** ± 1.750 orders per maand, ± 1,3 miljoen GA4-sessies (± 7 miljoen
events), ± 1,7 miljoen e-mailevents. Op schijf ± 0,5 GB; in BigQuery ± 10 GB.

**Kosten:** laden in BigQuery is gratis. Opslag valt grotendeels binnen de gratis 10 GiB per maand;
Cloud Storage kost een paar cent per maand. Zet wel een budgetalert op je project.

---

## Waarom Cloud Shell?

Je doet alles in **Cloud Shell**, de terminal in je browser in de Google Cloud-console. Daar staan Python,
`gcloud` en `bq` al klaar, en je bent al ingelogd met je eigen account. Je hoeft op je eigen computer
niets te installeren.

---

## Stappenplan

Neem de stappen één voor één. Na elke stap staat wat je zou moeten zien. Ziet het er anders uit, stop
dan en stuur de melding door; dan lossen we het samen op.

In de commando's staan twee waarden die je zelf invult:

- `JOUW_PROJECT` = de ID van je Google Cloud-project (bijvoorbeeld `mv-data-dev`)
- `JOUW_BUCKET` = de naam van de bucket die je in stap 5 maakt (bijvoorbeeld `mv-data-dev-bronnen`)

### Stap 1 — Cloud Shell openen en je project kiezen

1. Ga naar [console.cloud.google.com](https://console.cloud.google.com) en kies rechtsboven het icoon
   **Cloud Shell activeren** (`>_`). Onderin opent een terminal.
2. Typ en druk op Enter:

```bash
gcloud config set project JOUW_PROJECT
```

**Je ziet:** `Updated property [core/project].` Het project staat daarna in geel in de prompt.

### Stap 2 — Het pakket uploaden en uitpakken

1. Klik in de Cloud Shell-balk op de drie puntjes (**⋮**) → **Uploaden** en kies `mv-datagenerator.zip`.
2. Pak het uit en ga de map in:

```bash
cd ~
unzip -o mv-datagenerator.zip
cd mv-datagenerator
ls
```

**Je ziet:** `README.md  BRONNEN.md  VERVUILING.md  controleer.py  genereer.py  laad_backfill.sh  laad_dag.sh  schemas`

### Stap 3 — De data genereren

Controleer eerst je Python-versie (3.9 of hoger is nodig; Cloud Shell heeft een recente versie):

```bash
python3 --version
```


Eerst een korte proefrun (± 30 seconden) om te zien of alles werkt:

```bash
python3 genereer.py --schaal 0.1 --uitvoer ~/mv_proef
```

**Je ziet:** voortgangsregels per maand en aan het eind `Klaar in ... s`. Werkt dat, gooi de proef weg
en maak de echte set (± 5 tot 10 minuten; laat het tabblad open):

```bash
rm -rf ~/mv_proef
python3 genereer.py --uitvoer ~/mv_data
```

**Je ziet** aan het eind ongeveer: `Klaar in 300 s: 420 producten, 31.718 klantrijen, 44.589 orders, 7.478.552 GA4-events.`

> Dezelfde `--seed` geeft altijd exact dezelfde data. Wil je een andere webshop-werkelijkheid, gebruik dan
> bijvoorbeeld `--seed 7`.

### Stap 4 — De data controleren

```bash
python3 controleer.py --uitvoer ~/mv_data
```

Dit duurt ± 1 minuut. Het script controleert of de bronnen op elkaar aansluiten en sluit af met
**`Alles klopt.`** Bewaar de tabel onder kopje 7 (omzet, marge en kosten per kanaal): dat zijn de
cijfers waar je goudlaag straks ongeveer op moet uitkomen.

### Stap 5 — Een bucket maken in de EU

```bash
gcloud storage buckets create gs://JOUW_BUCKET --location=EU --uniform-bucket-level-access
```

**Je ziet:** `Creating gs://JOUW_BUCKET/...`. Een bucketnaam is wereldwijd uniek; krijg je
`409 ... already exists`, kies dan een andere naam (bijvoorbeeld met je project-ID ervoor).

> Waarom EU? Je BigQuery-datasets komen in de multi-region EU. Een load job leest het snelst en goedkoopst
> uit een bucket in dezelfde locatie, en je data blijft in Europa.

### Stap 6 — De bestanden uploaden

```bash
gcloud storage cp -r ~/mv_data/backfill ~/mv_data/dagelijks gs://JOUW_BUCKET/
gcloud storage du -s -r gs://JOUW_BUCKET
```

**Je ziet:** een voortgangsbalk en daarna de totale grootte (± 0,5 GB). De map `_antwoordsleutel`
upload je bewust níét: die hoort niet in je warehouse.

### Stap 7 — De bronslaag laden in BigQuery

```bash
bash laad_backfill.sh JOUW_PROJECT JOUW_BUCKET
```

Dit duurt ± 10 tot 15 minuten; het langst duren de 669 GA4-dagtabellen. Het script maakt de datasets
aan (locatie EU), laadt alle tabellen en toont aan het eind een tabel met het aantal rijen per tabel.

**Je ziet** onder andere:

| tabel | rijen (ongeveer) |
|---|---|
| raw_webshop.orders | 40.000 |
| raw_webshop.klanten | 29.000 |
| analytics_123456789.events_* (dagtabellen) | 669 |
| raw_email.events | 1.700.000 |

Wordt de verbinding verbroken? Draai het script gewoon opnieuw: elke tabel wordt vervangen.

### Stap 8 — Kijken in BigQuery

Open BigQuery in de console. Links in de verkenner zie je onder je project de datasets `raw_webshop`,
`analytics_123456789`, `raw_ads`, `raw_email` en `raw`. Probeer:

```sql
-- orders per maand in de bron
SELECT FORMAT_TIMESTAMP('%Y-%m', besteld_op, 'Europe/Amsterdam') AS maand, COUNT(*) AS orders
FROM `JOUW_PROJECT.raw_webshop.orders`
GROUP BY maand
ORDER BY maand;
```

Vanaf hier ben je in fase 4 van de gids: de bronslaag verkennen en valideren.

### Stap 9 (later) — Dagelijkse leveringen verwerken

In de map `dagelijks/` staat voor elke dag van november 2026 wat er die dag binnenkomt: nieuwe en
gewijzigde orders, de GA4-tabellen van gisteren (voorlopig) en eergisteren (definitief), de Google Ads-
en Meta-cijfers van de laatste 7 dagen, de e-mails van gisteren en af en toe een nieuwe prijslijst.
Daarmee oefen je incrementeel laden in je zilver- en goudlaag.

```bash
bash laad_dag.sh JOUW_PROJECT JOUW_BUCKET 2026-11-01
bash laad_dag.sh JOUW_PROJECT JOUW_BUCKET 2026-11-02
```

Verwerk de dagen op volgorde. Je kunt ze één voor één doen (bijvoorbeeld één per dag, alsof de tijd
echt verstrijkt) of meerdere achter elkaar met een lus:

```bash
for d in 2026-11-0{1..7}; do bash laad_dag.sh JOUW_PROJECT JOUW_BUCKET "$d"; done
```

---

## Wat staat waar

```text
mv-datagenerator/
├── genereer.py          de generator (alleen standaard-Python, geen extra pakketten)
├── controleer.py        controles vóór het uploaden
├── laad_backfill.sh     laadt de historische lading in BigQuery
├── laad_dag.sh          verwerkt één dagelijkse levering
├── schemas/             BigQuery-schema's per brontabel
├── BRONNEN.md           de "broninterviews": wat je van elke bron weet (fase 1)
└── VERVUILING.md        spiekbrief met alle ingebouwde vervuiling (pas lezen ná het profileren!)

~/mv_data/               (na stap 3)
├── backfill/            stand per 31-10-2026: webshop/ ga4/ google_ads/ meta/ email/ leveranciers/
├── dagelijks/           2026-11-01/ ... 2026-11-30/
└── _antwoordsleutel/    de "waarheid" per order (echt kanaal, inkoopwaarde) om je warehouse te toetsen
```

## Aanpassen

Bovenin `genereer.py` staat `CONFIG` met de periode, het aantal sessies, de groei en de ID's. Daaronder
staan de kanalen, de campagnes (met conversiekans en klikprijs), het seizoenspatroon en de catalogus.
Wil je minder data, gebruik dan `--schaal 0.5`. Een goede eerste oefening met Claude Code: vraag het
een extra bron toe te voegen (bijvoorbeeld productreviews) of een nieuwe vervuilingsregel in te bouwen.

## Als er iets misgaat

| Melding | Oorzaak | Oplossing |
|---|---|---|
| `python3: can't open file 'genereer.py'` | Je staat niet in de map | `cd ~/mv-datagenerator` |
| `... backfill bestaat al` | Er staat al data in die map | `rm -rf ~/mv_data` en opnieuw genereren |
| `AccessDeniedException: 403` | Verkeerd project of onvoldoende rechten | Controleer stap 1; je hebt de rol BigQuery Admin en Storage Admin (of Owner) nodig |
| `Not found: Dataset` | Dataset in een andere locatie | Verwijder de dataset en laat het script hem opnieuw (in EU) maken |
| `Cloud Shell ... disconnected` | Sessie verlopen | Opnieuw verbinden en het laatste commando opnieuw draaien |
| `Error while reading data ... JSON` | Bestand niet volledig geüpload | Stap 6 opnieuw, daarna stap 7 |
| `Killed` tijdens het genereren | Cloud Shell heeft te weinig geheugen vrij (de generator gebruikt ± 0,8 GB) | `rm -rf ~/mv_data` en genereer met `--schaal 0.5` |
