# Spiekbrief: ingebouwde vervuiling

> **Lees dit pas nadat je de bronnen zelf hebt geprofileerd (fase 5, stap 1).** Het doel is dat je de
> problemen zelf vindt, net als bij een echte klant. Daarna gebruik je deze lijst om te controleren of je
> niets hebt gemist. De laatste kolom verwijst naar de opschoontechniek in hoofdstuk 7 van de gids.

## Webshop

| Tabel | Vervuiling | Hoe vaak | Techniek |
|---|---|---|---|
| klanten | Gastbestellingen krijgen elke keer een nieuwe `klant_id` met hetzelfde e-mailadres | ± 30% van de nieuwe klanten is gast | Ontdubbelen op genormaliseerde e-mailhash ("persoon" naast "account") |
| klanten | E-mail met hoofdletter, spatie voor of achter, of helemaal in hoofdletters | ± 9% | `LOWER(TRIM())` vóór het hashen |
| klanten | Postcode als `1234 AB`, `1234AB` of `1234ab`; Belgische postcodes zonder letters | 30% afwijkend | `UPPER(REPLACE(TRIM()))` |
| klanten | `plaats` met spatie achteraan, in hoofdletters, of `'s-Gravenhage` voor Den Haag | ± 5% + 15% van Den Haag | `TRIM`, mappingtabel |
| klanten | `land` als `NL`, `Nederland`, `nl`, `NLD`, `The Netherlands`, NULL; `BE`, `België`, `Belgie`, `be`, `BEL` | ± 25% afwijkend | Mappingtabel `map_landen` |
| klanten | `nieuwsbrief_opt_in` is NULL | ± 3% | `IFNULL` / onbekend |
| klanten | Opt-in blijft `true` na afmelden in het e-mailplatform | ± 0,25% per verzonden nieuwsbrief | Leidende bron: e-mailplatform |
| klanten | Testaccount `test@marktvizier.example` | 1 klant | Uitsluiten |
| orders | Status `pending`, `paid`, `Paid`, `shipped`, `returned`, `canceled` (tot sept 2025) / `cancelled` (daarna) | `Paid` ± 1% | `LOWER(TRIM())` + `CASE` |
| orders | Nieuwe status `on_hold` sinds 15 september 2026 | ± 1,2% van de orders daarna | `ELSE 'onbekend'` + teller |
| orders | `betaalmethode` als `ideal` en `iDEAL` | ± 8% | `LOWER` |
| orders | `kortingscode` leeg als NULL óf `''`; `BF25`, `bf25`, `BF25 ` | overal | `NULLIF(UPPER(TRIM()), '')` |
| orders | `verzonden_op` vóór `besteld_op` | ± 0,5% van de verzonden orders | Ongeldige volgorde → NULL |
| orders | Testorders (`is_testorder = true`) | ± 0,4% | Uitsluiten |
| orders | Gaten in de ordernummering | ± 20% | Niets doen: geen fout |
| orderregels | Negatieve `stukprijs_incl_btw` (tekenfout) | ± 0,2% | `ABS()` |
| orderregels | `regelbedrag_incl_btw` = 0 | ± 0,3% | Herberekenen: aantal × prijs − korting |
| orderregels | `regelbedrag_incl_btw` met dubbele btw (× 1,21) | ± 0,2% | Bedrijfsregel aantal × prijs |
| orderregels | `korting_incl_btw` NULL óf 0 als er geen korting is | ± 50/50 | `IFNULL(…, 0)` |
| producten | Elke wijziging is een nieuwe rij (append-only): prijs, categorie (± 5% wisselt), label, uitfasering | ± 1.200 rijen voor 420 producten | Laatste versie (`QUALIFY`) of SCD 2 |
| producten | Productnamen met é, è (Café-tafel, crème, écru) | | Let op codering bij leveranciers |

**In de dagelijkse leveringen extra:** meerdere versies van dezelfde order op één dag, en ± 5% van de
klantrijen komt exact dubbel binnen.

## GA4

| Vervuiling | Hoe vaak | Techniek |
|---|---|---|
| `transaction_id` krijgt sinds 1 maart 2026 het voorvoegsel `MV-` (nieuw thema) | alle orders daarna | `REPLACE(transaction_id, 'MV-', '')` vóór de join |
| Sessies zonder meting (geen cookietoestemming) en telefonische orders | ± 9% van de orders niet in GA4 | Kanaal "Onbekend"; koppelpercentage bewaken |
| Dubbel `purchase`-event (bedankpagina opnieuw geladen) | ± 1,5% van de orders | Ontdubbelen op `transaction_id` |
| Google Ads-sessies hebben meestal alleen `gclid`, geen UTM | ± 70% | Koppelen via `ads_ClickStats.click_view_gclid` |
| Meta-UTM's: `utm_source` facebook / Facebook / fb / instagram / ig; `utm_medium` paid_social / cpc / Paid Social | overal | `LOWER` + regex in kanaalindeling |
| Meta-campagnenaam in UTM als slug (`prospecting_lookalike_kopers`) of letterlijk; soms `manual_campaign_id` | 80/20; ID ± 50% | Koppelen op ID waar mogelijk, anders op slug |
| E-mail-UTM's: `nieuwsbrief` / `klaviyo` / `Nieuwsbrief`; medium `email` / `e-mail` / `Email`; campagne als slug | overal | Kanaalindeling; slug ↔ campagnenaam |
| Organisch en verwijzingen: bron en medium alleen in `event_params` (`source`, `medium`), niet in `collected_traffic_source` | overal | `COALESCE` uit beide |
| `traffic_source` is de eerste aanraking van de gebruiker, niet van de sessie | overal | Niet gebruiken voor sessie-attributie |
| `user_id` alleen op `begin_checkout` en `purchase` van ingelogde klanten | | Niet als sessiesleutel gebruiken |
| Late events: ± 3% van de events zit alleen in de definitieve versie van een dagtabel | alleen dagelijkse leveringen | Laatste 3 dagen opnieuw verwerken |

## Google Ads

| Vervuiling | Techniek |
|---|---|
| Kosten in micro-eenheden | `/ 1e6` |
| `ads_Campaign` is een dagelijkse momentopname: elke campagne staat er elke dag in | Laatste stand per `campaign_id` |
| Campagne hernoemd op 1 februari 2026 (PMax \| Algemeen → PMax \| Alle producten) | Naam uit de laatste momentopname; koppelen op ID |
| Conversies en conversiewaarde (incl. btw) hoger dan de webshop | Niet gebruiken als omzet; webshop is leidend |
| ± 10% van de kliks heeft geen GA4-sessie | Normaal: niet elke klik laadt de pagina |
| Dagelijks: de cijfers van gisteren zijn in de eerste levering iets te hoog en worden later gecorrigeerd | 7 dagen opnieuw laden |

## Meta Ads

| Vervuiling | Techniek |
|---|---|
| `spend` en `action_values_purchase` als tekst | `CAST(… AS NUMERIC)` |
| `campaign_id` als tekst van 18 cijfers | Als tekst houden (geen INT64-afronding in BI-tools) |
| Pixelaankopen 10–60% hoger dan de webshop | Niet gebruiken als omzet |
| Dagelijks: cijfers van gisteren wijzigen nog | 7 dagen opnieuw laden |

## E-mailplatform

| Vervuiling | Techniek |
|---|---|
| Alles in een JSON-payload | `JSON_VALUE(payload, '$.profile.email')` enz. |
| `timestamp` in lokale tijd met offset `+01:00` / `+02:00` (zomertijd) | `TIMESTAMP(JSON_VALUE(…))` zet om naar UTC |
| `profile.email` precies zoals ingetypt (hoofdletters, spaties) | Normaliseren vóór hashen |
| `external_id` (klant_id als tekst) alleen als het adres al aan een klant gekoppeld is; popup-inschrijvers zonder order hebben NULL | Koppelen via e-mailhash |
| Eventnamen in het Engels (`Subscribed to List`, `Unsubscribed`) | Vertalen naar `aangemeld` / `afgemeld` |
| Nieuwsbriefnaam (`Nieuwsbrief wk 12 - Lente in huis`) ≠ UTM-slug (`nieuwsbrief_wk12_lente_in_huis`) | Mappingtabel of slugfunctie |

## Leveranciers

| Vervuiling | Techniek |
|---|---|
| Noorderlicht stuurt elke week de hele lijst: dezelfde prijs staat tientallen keren in de tabel | Ontdubbelen op artikelnummer + geldig_vanaf |
| Hout & Heem: Windows-codering (é wordt anders onleesbaar) | `encoding='ISO-8859-1'` bij laden |
| Hout & Heem: decimale komma, datum DD-MM-JJJJ, `Ja`/`Nee` | `SAFE_CAST(REPLACE(…, ',', '.') AS NUMERIC)`, `SAFE.PARSE_DATE('%d-%m-%Y', …)` |
| Hout & Heem: artikelcode in kleine letters (`hh-20311`) | `UPPER()` vóór de join met `producten.sku` |
| Hout & Heem: lege prijs (± 1%) of `0,00` (± 0,5%) | Quarantaine / afkeuren |
| Hout & Heem: extra kolom `Levertijd (dagen)` sinds juni 2026 | Laden met `allow_jagged_rows` |
| Producten staan soms al op de prijslijst tot 30 dagen vóór de lancering in de shop | Geen fout; let op bij dekkingscontroles |

## Wat er níét vervuild is (zodat je weet waar je niet hoeft te zoeken)

- De koppeling `orderregels.product_id` → `producten.product_id` is altijd te leggen.
- Elke `gclid` in GA4 staat in `ads_ClickStats`.
- Elk product heeft een inkoopprijs bij één van de twee leveranciers.
