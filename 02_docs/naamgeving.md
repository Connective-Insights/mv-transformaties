

| Onderdeel | SQL Server Klant DWH | BigQuery Klant DWH | Waarom |
| :--- | :--- | :--- | :--- |
| Algemeen | snake_case, kleine letters, Nederlands, geen gereserveerde woorden | snake_case, kleine letters, Nederlands voor eigen objecten; brontabellen houden hun naam | BigQuery is hoofdlettergevoelig in tabelnamen; Nederlands sluit aan bij de gebruikers |
| Brons| (bron)_(entiteit), naam zoals in de bron | Dataset **raw_(bron)**, tabel zoals de innamedienst hem maakt | Datastream, DTS en GA4 kiezen zelf tabelnamen; die niet hernoemen houdt brons herleidbaar |
| Zilver | (bron)_(entiteit), naam zoals in de bron | stg_(entiteit) in dataset staging; bij meerdere bronnen stg_(bron)_(entiteit) | Het voorvoegsel stg_ maakt de laag zichtbaar, ook in Dataform-grafieken en join-code |
| Goud | dim_, fact_, report_ | dim_, fct_, mart_, rpt_ in dataset marts | **mart_** voor brede, geaggregeerde tabellen per onderwerp; **rpt_** voor één rapport |
| Surrogaatsleutel | (tabel)_key | (entiteit)_key  | Ongewijzigd: herkenbaar en eenduidig |
| Technische kolommen | dwh_(naam) | **dwh_(naam)** (bijv. dwh_geladen_op, dwh_bron) | Ongewijzigd: scheidt systeemkolommen van bedrijfskolommen |
| Procedures  | load_(laag)| Geen procedures; Dataform-tags staging en marts | Dataform bepaalt de volgorde; tags maken een laag apart uitvoerbaar |
| Datums en tijden | (niet benoemd) | **(gebeurtenis)_op** voor TIMESTAMP, **(gebeurtenis)_datum** voor DATE | Het datatype is aan de naam te zien: besteld_op vs besteld_datum |
| Bedragen | (niet benoemd) | Altijd _excl_btw of _incl_btw in de naam | Voorkomt de duurste fout in e-commerce-BI |
| Vlaggen | (niet benoemd) | **is_(eigenschap)** of **heeft_(eigenschap)**, type BOOL | is_nieuwe_klant leest als een vraag met ja/nee-antwoord |

**Technische kolommen:**
Elke tabel in zilver en goud krijgt een paar kolommen die niets met het bedrijf te maken hebben, maar alles met herleidbaarheid. Op **Google Cloud** zijn drie erg nuttig:


| Kolom | Type | Inhoud | Waarvoor |
| :--- | :--- | :--- | :--- |
| dwh_geladen_op | TIMESTAMP | Moment waarop de rij in deze laag terechtkwam | Debuggen, incrementeel laden, versheidscontrole |
| dwh_bron | STRING | Bronsysteem (webshop, ga4, google_ads) | Herkomst bij geïntegreerde tabellen |
| dwh_run_id | STRING | ID van de Dataform-uitvoering | Een foute run terugvinden en terugdraaien |

