# Broninterviews MarktVizier (fase 1)

Dit is wat de eigenaren van de bronnen je in een interview zouden vertellen. Gebruik het als basis voor
je eigen broninterviews in `docs/01_requirements/broninterviews/`. De vragen volgen Baraa's vragenlijst
(context en eigenaarschap, architectuur en techniek, extract en load).

Let op: eigenaren vertellen nooit alles. Wat zij níét weten, ontdek je zelf bij het profileren in fase 5.
De volledige lijst staat in `VERVUILING.md`; lees die pas daarna.

---

## 1. Webshopdatabase

| Vraag | Antwoord |
|---|---|
| Eigenaar | IT / het webbureau dat de shop onderhoudt |
| Bedrijfsproces | Bestellen, betalen, verzenden, retourneren; klantaccounts |
| Systeem en opslag | Cloud SQL for PostgreSQL (`mv-orders-db`), database van de webshopsoftware |
| Integratie | Datastream (CDC) naar BigQuery, merge-modus; producten in append-only-modus (elke versie een rij) |
| Tabellen | `orders`, `orderregels`, `klanten`, `producten` |
| Sleutels | `order_id`, (`order_id`, `regel_nr`), `klant_id`, `product_id` (en `sku` als artikelnummer) |
| Volume | ± 1.800 orders per maand, ± 1,5 regel per order; ± 30.000 klantrijen |
| Historie | Vanaf januari 2025 (oudere orders zijn bij de migratie naar deze shop niet meegenomen) |
| Bedragen | In euro's **inclusief** btw; btw-tarief per regel (21%, kruidenplanten 9%) |
| Tijden | TIMESTAMP in UTC |
| Toegang | Via Datastream; geen directe querytoegang voor het datateam |

**Wat de eigenaar zelf noemt:**

- Bij een gastbestelling maakt de shop elke keer een nieuwe klantrij aan, ook als dezelfde persoon al eerder bestelde.
- Er is een testaccount waarmee het webbureau bestellingen test; die orders hebben `is_testorder = true`.
- Orders veranderen na het plaatsen van status: betaald, verzonden, geannuleerd, geretourneerd.
- In september 2025 is de shopsoftware bijgewerkt; "er is toen wat aan de statussen veranderd".
- Verzendkosten: € 4,95 onder de € 75, daarboven gratis.

---

## 2. GA4

| Vraag | Antwoord |
|---|---|
| Eigenaar | Online marketing |
| Systeem | GA4-property 123456789, webstream `www.marktvizier.example` |
| Integratie | Native BigQuery-export, dagelijks (dataset `analytics_123456789`) |
| Volume | ± 60.000 sessies en ± 300.000 events per maand |
| Historie | Vanaf januari 2025 |
| Tijden | `event_timestamp` in microseconden UTC; `event_date` in Nederlandse tijd |
| Bedragen | `purchase`-waarde inclusief btw, exclusief verzendkosten |

**Wat de eigenaar zelf noemt:**

- Niet iedereen geeft toestemming voor cookies, dus GA4 ziet niet alle bezoeken en aankopen.
- Google Ads gebruikt auto-tagging (`gclid`); een deel van de campagnes heeft daarnaast UTM-parameters.
- Meta- en e-mailcampagnes worden getagd met UTM-parameters, "maar niet iedereen doet dat even netjes".
- In maart 2026 is een nieuw thema op de webshop gezet; de tracking is toen opnieuw ingericht.
- Een dagtabel kan tot ± 3 dagen na de dag nog worden bijgewerkt.

---

## 3. Google Ads

| Vraag | Antwoord |
|---|---|
| Eigenaar | Online marketing |
| Integratie | BigQuery Data Transfer Service, klant-ID 123-456-7890, refresh window 7 dagen |
| Tabellen | `ads_Campaign_1234567890` (dagelijkse momentopname van de campagnes), `ads_CampaignBasicStats_1234567890` (dag × campagne × apparaat), `ads_ClickStats_1234567890` (één rij per klik, met `gclid`) |
| Campagnes | Merk, Generiek, Shopping bestsellers, Performance Max, Shopping tuin (seizoen), Black Friday |
| Bedragen | Kosten in micro-eenheden (`metrics_cost_micros` / 1.000.000 = euro) |

**Wat de eigenaar zelf noemt:**

- "Google Ads rapporteert altijd meer conversies dan de webshop. Dat komt door de attributie van Google."
- De Black Friday- en tuincampagnes staan buiten hun seizoen op pauze.
- In februari 2026 is de Performance Max-campagne hernoemd.

---

## 4. Meta Ads

| Vraag | Antwoord |
|---|---|
| Eigenaar | Online marketing |
| Integratie | DTS-connector Facebook Ads; levert een CSV met dagstatistieken per campagne |
| Velden | `date_start`, `campaign_id`, `campaign_name`, `impressions`, `clicks`, `spend`, `actions_purchase`, `action_values_purchase` |
| Bedragen | Euro's; de API levert bedragen als tekst |
| Campagnes | Prospecting (2), retargeting (2), Black Friday |

**Wat de eigenaar zelf noemt:**

- Meta telt aankopen via de pixel en rapporteert er "flink meer" dan de webshop.
- Cijfers van gisteren kunnen de volgende dagen nog iets wijzigen.

---

## 5. E-mailplatform

| Vraag | Antwoord |
|---|---|
| Eigenaar | CRM-marketeer |
| Integratie | Eigen Cloud Run job haalt elke nacht de events van gisteren op via de API; elk event komt als JSON-payload binnen |
| Events | `Received Email`, `Opened Email`, `Clicked Email`, `Subscribed to List`, `Unsubscribed` |
| Campagnes | Wekelijkse nieuwsbrief (donderdag 10:00) en een welkomstflow bij inschrijving |
| Volume | ± 75.000 events per maand, groeiend met het aantal abonnees |
| Tijden | `timestamp` in lokale tijd met offset (bijvoorbeeld `+01:00`) |

**Wat de eigenaar zelf noemt:**

- Afmeldingen gaan alleen in het e-mailplatform; "volgens mij wordt dat niet teruggezet in de webshop".
- Klikken in een nieuwsbrief krijgen UTM-parameters met de campagnenaam erin.
- Mensen typen hun e-mailadres zelf in, dus "er zit van alles tussen".

---

## 6. Leveranciers

| | Noorderlicht Textiel | Hout & Heem |
|---|---|---|
| Producten | Textiel, slapen, badkamer (artikelnummers `NL-…`) | Wonen, keuken, tuin, verlichting (`HH-…`) |
| Levering | Elke maandag een volledige prijslijst | Elke 1e van de maand een volledige prijslijst |
| Bestand | `prijzen_JJJJMMDD.csv` | `prijslijst_JJJJ-MM.csv` |
| Formaat | UTF-8, puntkomma, punt als decimaalteken, datum JJJJ-MM-DD | Excel-export, puntkomma, komma als decimaalteken, datum DD-MM-JJJJ |
| Inhoud | artikelnummer, omschrijving, inkoopprijs, geldig_vanaf, eenheid | Artikelcode, Omschrijving, Inkoopprijs (EUR), Geldig vanaf, Op voorraad |

**Wat de eigenaren zelf noemen:**

- Noorderlicht: "elke week de hele lijst, ook als er niets verandert".
- Hout & Heem: "we halen het uit Excel en slaan het op". Sinds juni 2026 staat er een kolom met de levertijd bij.

---

## Afspraken uit het requirements-gesprek

- De **webshopdatabase is de bron van waarheid voor omzet**; GA4 levert alleen de herkomst (kanaal, campagne).
- Omzet rapporteren we **exclusief btw**, zonder verzendkosten, zonder geannuleerde orders en testorders.
- Marge = omzet excl. btw − aantal × **inkoopprijs die gold op de besteldatum**.
- Kanaal = laatste klik volgens GA4; orders zonder GA4-sessie krijgen kanaal **Onbekend**.
