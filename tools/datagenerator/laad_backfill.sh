#!/usr/bin/env bash
# =============================================================================================
# Laadt de historische lading (backfill, t/m 31-10-2026) uit Cloud Storage in BigQuery.
# Dit script speelt de rol van de echte connectors: Datastream, de GA4-export, BigQuery DTS
# (Google Ads, Facebook Ads), de Cloud Run job van het e-mailplatform en de leveranciersupload.
#
# Gebruik (in Cloud Shell, vanuit de map mv-datagenerator):
#     bash laad_backfill.sh <project-id> <bucketnaam>
# Voorbeeld:
#     bash laad_backfill.sh mv-data-dev mv-data-dev-bronnen
#
# Load jobs zijn gratis. Het script mag je opnieuw draaien: elke tabel wordt vervangen (--replace).
# =============================================================================================
set -euo pipefail

PROJECT="${1:?Geef je project-id op, bijvoorbeeld: bash laad_backfill.sh mv-data-dev mv-data-dev-bronnen}"
BUCKET="${2:?Geef je bucketnaam op (zonder gs://)}"
BRON="gs://${BUCKET}/backfill"
LOC="EU"
GA4_DATASET="analytics_123456789"
ADS_ID="1234567890"
SCHEMA="$(cd "$(dirname "$0")" && pwd)/schemas"
export PROJECT LOC GA4_DATASET SCHEMA

echo "Project: ${PROJECT}   bron: ${BRON}   locatie: ${LOC}"
echo

echo "== 1/7  Datasets aanmaken (locatie ${LOC}) =="
for ds in raw_webshop "${GA4_DATASET}" raw_ads raw_email raw; do
  bq --location="${LOC}" mk --force --dataset "${PROJECT}:${ds}" >/dev/null
  echo "   ${ds}"
done

# hulpfunctie: laad één tabel; extra bq-opties mogen na de drie vaste argumenten
laad() {
  local tabel="$1" bron="$2" schema="$3"; shift 3
  bq -q --location="${LOC}" load --replace "$@" "${PROJECT}:${tabel}" "${bron}" "${SCHEMA}/${schema}.json"
  echo "   ${tabel}"
}

echo
echo "== 2/7  Webshop (zoals Datastream het neerzet) =="
laad raw_webshop.klanten     "${BRON}/webshop/klanten.ndjson.gz"     webshop_klanten     --source_format=NEWLINE_DELIMITED_JSON
laad raw_webshop.orders      "${BRON}/webshop/orders.ndjson.gz"      webshop_orders      --source_format=NEWLINE_DELIMITED_JSON
laad raw_webshop.orderregels "${BRON}/webshop/orderregels.ndjson.gz" webshop_orderregels --source_format=NEWLINE_DELIMITED_JSON
laad raw_webshop.producten   "${BRON}/webshop/producten.ndjson.gz"   webshop_producten   --source_format=NEWLINE_DELIMITED_JSON

echo
echo "== 3/7  GA4-export: één tabel per dag (events_JJJJMMDD), 8 tegelijk; dit duurt ± 10 minuten =="
laad_ga4() {
  local bestand="$1"
  local tabel
  tabel="$(basename "${bestand}" .ndjson.gz)"
  bq -q --location="${LOC}" load --replace --source_format=NEWLINE_DELIMITED_JSON \
    "${PROJECT}:${GA4_DATASET}.${tabel}" "${bestand}" "${SCHEMA}/ga4_events.json" && echo "   ${tabel}"
}
export -f laad_ga4
gcloud storage ls "${BRON}/ga4/" | grep -E 'events_[0-9]{8}\.ndjson\.gz$' | xargs -P 8 -n 1 bash -c 'laad_ga4 "$0"'

echo
echo "== 4/7  Google Ads (zoals BigQuery DTS het neerzet) =="
laad "raw_ads.ads_Campaign_${ADS_ID}"           "${BRON}/google_ads/ads_Campaign_${ADS_ID}.ndjson.gz"           ads_Campaign \
  --source_format=NEWLINE_DELIMITED_JSON --time_partitioning_type=DAY --time_partitioning_field=_DATA_DATE
laad "raw_ads.ads_CampaignBasicStats_${ADS_ID}" "${BRON}/google_ads/ads_CampaignBasicStats_${ADS_ID}.ndjson.gz" ads_CampaignBasicStats \
  --source_format=NEWLINE_DELIMITED_JSON --time_partitioning_type=DAY --time_partitioning_field=segments_date
laad "raw_ads.ads_ClickStats_${ADS_ID}"         "${BRON}/google_ads/ads_ClickStats_${ADS_ID}.ndjson.gz"         ads_ClickStats \
  --source_format=NEWLINE_DELIMITED_JSON --time_partitioning_type=DAY --time_partitioning_field=segments_date

echo
echo "== 5/7  Meta Ads =="
laad raw_ads.meta_ad_insights "${BRON}/meta/meta_ad_insights.csv" meta_ad_insights \
  --source_format=CSV --skip_leading_rows=1

echo
echo "== 6/7  E-mailplatform (zoals de Cloud Run job het neerzet) =="
laad raw_email.events "${BRON}/email/events_*.ndjson.gz" email_events \
  --source_format=NEWLINE_DELIMITED_JSON --time_partitioning_type=DAY --time_partitioning_field=geladen_voor_datum

echo
echo "== 7/7  Leveranciersbestanden =="
laad raw.prijzen_noorderlicht "${BRON}/leveranciers/noorderlicht/*.csv" prijzen_noorderlicht \
  --source_format=CSV --skip_leading_rows=1 --field_delimiter=';'
laad raw.prijzen_houtheem "${BRON}/leveranciers/houtheem/*.csv" prijzen_houtheem \
  --source_format=CSV --skip_leading_rows=1 --field_delimiter=';' --encoding=ISO-8859-1 --allow_jagged_rows

echo
echo "== Controle: aantal rijen per tabel =="
bq -q --location="${LOC}" query --use_legacy_sql=false --format=pretty "
SELECT 'raw_webshop.klanten' AS tabel, COUNT(*) AS rijen FROM \`${PROJECT}.raw_webshop.klanten\`
UNION ALL SELECT 'raw_webshop.orders', COUNT(*) FROM \`${PROJECT}.raw_webshop.orders\`
UNION ALL SELECT 'raw_webshop.orderregels', COUNT(*) FROM \`${PROJECT}.raw_webshop.orderregels\`
UNION ALL SELECT 'raw_webshop.producten', COUNT(*) FROM \`${PROJECT}.raw_webshop.producten\`
UNION ALL SELECT '${GA4_DATASET}.events_* (dagtabellen)', COUNT(DISTINCT _TABLE_SUFFIX) FROM \`${PROJECT}.${GA4_DATASET}.events_*\`
UNION ALL SELECT 'raw_ads.ads_CampaignBasicStats', COUNT(*) FROM \`${PROJECT}.raw_ads.ads_CampaignBasicStats_${ADS_ID}\`
UNION ALL SELECT 'raw_ads.ads_ClickStats', COUNT(*) FROM \`${PROJECT}.raw_ads.ads_ClickStats_${ADS_ID}\`
UNION ALL SELECT 'raw_ads.meta_ad_insights', COUNT(*) FROM \`${PROJECT}.raw_ads.meta_ad_insights\`
UNION ALL SELECT 'raw_email.events', COUNT(*) FROM \`${PROJECT}.raw_email.events\`
UNION ALL SELECT 'raw.prijzen_noorderlicht', COUNT(*) FROM \`${PROJECT}.raw.prijzen_noorderlicht\`
UNION ALL SELECT 'raw.prijzen_houtheem', COUNT(*) FROM \`${PROJECT}.raw.prijzen_houtheem\`
ORDER BY tabel"

echo
echo "Klaar. De bronslaag staat in BigQuery. Vergelijk de aantallen met de uitvoer van controleer.py."
