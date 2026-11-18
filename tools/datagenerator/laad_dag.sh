#!/usr/bin/env bash
# =============================================================================================
# Verwerkt de levering van één dag (november 2026) zoals de connectors dat zouden doen.
#
# Gebruik (in Cloud Shell, vanuit de map mv-datagenerator):
#     bash laad_dag.sh <project-id> <bucketnaam> <datum>
# Voorbeeld:
#     bash laad_dag.sh mv-data-dev mv-data-dev-bronnen 2026-11-01
#
# Wat er per bron gebeurt (en wat de echte dienst doet):
#   webshop       wijzigingen samenvoegen in raw_webshop (Datastream, merge-modus)
#                 producten worden toegevoegd (append-only, met change_type)
#   GA4           dagtabellen van gisteren (voorlopig) en eergisteren (definitief) vervangen
#   Google Ads    laatste 7 dagen vervangen (DTS refresh window)
#   Meta Ads      laatste 7 dagen vervangen
#   e-mail        events van gisteren toevoegen (Cloud Run job)
#   leveranciers  nieuwe prijslijst toevoegen als die er die dag is
#
# Het script is idempotent voor webshop, GA4, advertenties en e-mail: draai je dezelfde dag twee keer,
# dan verandert er niets. Leveranciersprijslijsten worden toegevoegd; dubbel draaien geeft dubbele rijen
# (die vang je in zilver af met ontdubbelen, net als bij een leverancier die een bestand twee keer stuurt).
# Verwerk de dagen op volgorde: 2026-11-01, 2026-11-02, ...
# =============================================================================================
set -euo pipefail

PROJECT="${1:?Geef je project-id op}"
BUCKET="${2:?Geef je bucketnaam op (zonder gs://)}"
DAG="${3:?Geef de datum op, bijvoorbeeld 2026-11-01}"
BRON="gs://${BUCKET}/dagelijks/${DAG}"
LOC="EU"
GA4_DATASET="analytics_123456789"
ADS_ID="1234567890"
SCHEMA="$(cd "$(dirname "$0")" && pwd)/schemas"

if ! gcloud storage ls "${BRON}/" >/dev/null 2>&1; then
  echo "Geen levering gevonden op ${BRON}/ — staat de map dagelijks/ wel in je bucket?"
  exit 1
fi
echo "Levering ${DAG}  (${BRON})"

bestaat() { gcloud storage ls "$1" >/dev/null 2>&1; }

# laad een bestand in een tijdelijke deltatabel
laad_delta() {
  local tabel="$1" bron="$2" schema="$3"; shift 3
  bq -q --location="${LOC}" load --replace "$@" "${PROJECT}:${tabel}" "${bron}" "${SCHEMA}/${schema}.json"
}

# vervang rijen in de doeltabel door de (ontdubbelde) rijen uit de deltatabel, op sleutel
voeg_samen() {
  local doel="$1" delta="$2" sleutel="$3" volgorde="$4"
  bq -q --location="${LOC}" query --use_legacy_sql=false "
BEGIN TRANSACTION;
DELETE FROM \`${PROJECT}.${doel}\`
WHERE ${sleutel} IN (SELECT ${sleutel} FROM \`${PROJECT}.${delta}\`);
INSERT INTO \`${PROJECT}.${doel}\`
SELECT * EXCEPT (_rn)
FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY ${sleutel} ORDER BY ${volgorde} DESC) AS _rn
  FROM \`${PROJECT}.${delta}\`
)
WHERE _rn = 1;
COMMIT TRANSACTION;" >/dev/null
  bq -q rm -f -t "${PROJECT}:${delta}"
  echo "   ${doel}"
}

echo "== Webshop =="
for t in klanten orders orderregels; do
  if bestaat "${BRON}/webshop/${t}.ndjson.gz"; then
    laad_delta "raw_webshop.delta_${t}" "${BRON}/webshop/${t}.ndjson.gz" "webshop_${t}" --source_format=NEWLINE_DELIMITED_JSON
    case "${t}" in
      klanten)     sleutel="klant_id" ;;
      orders)      sleutel="order_id" ;;
      orderregels) sleutel="CONCAT(CAST(order_id AS STRING), '-', CAST(regel_nr AS STRING))" ;;
    esac
    voeg_samen "raw_webshop.${t}" "raw_webshop.delta_${t}" "${sleutel}" "datastream_metadata.source_timestamp"
  fi
done
if bestaat "${BRON}/webshop/producten.ndjson.gz"; then
  laad_delta "raw_webshop.delta_producten" "${BRON}/webshop/producten.ndjson.gz" webshop_producten --source_format=NEWLINE_DELIMITED_JSON
  voeg_samen "raw_webshop.producten" "raw_webshop.delta_producten" "datastream_metadata.uuid" "datastream_metadata.source_timestamp"
fi

echo "== GA4 =="
if bestaat "${BRON}/ga4/"; then
  for bestand in $(gcloud storage ls "${BRON}/ga4/" | grep -E 'events_[0-9]{8}\.ndjson\.gz$'); do
    tabel="$(basename "${bestand}" .ndjson.gz)"
    bq -q --location="${LOC}" load --replace --source_format=NEWLINE_DELIMITED_JSON \
      "${PROJECT}:${GA4_DATASET}.${tabel}" "${bestand}" "${SCHEMA}/ga4_events.json"
    echo "   ${GA4_DATASET}.${tabel}"
  done
fi

echo "== Google Ads =="
if bestaat "${BRON}/google_ads/ads_CampaignBasicStats_${ADS_ID}.ndjson.gz"; then
  laad_delta raw_ads.delta_stats "${BRON}/google_ads/ads_CampaignBasicStats_${ADS_ID}.ndjson.gz" ads_CampaignBasicStats --source_format=NEWLINE_DELIMITED_JSON
  voeg_samen "raw_ads.ads_CampaignBasicStats_${ADS_ID}" raw_ads.delta_stats \
    "CONCAT(CAST(campaign_id AS STRING), '|', CAST(segments_date AS STRING), '|', segments_device)" "metrics_clicks"
fi
if bestaat "${BRON}/google_ads/ads_ClickStats_${ADS_ID}.ndjson.gz"; then
  laad_delta raw_ads.delta_clicks "${BRON}/google_ads/ads_ClickStats_${ADS_ID}.ndjson.gz" ads_ClickStats --source_format=NEWLINE_DELIMITED_JSON
  voeg_samen "raw_ads.ads_ClickStats_${ADS_ID}" raw_ads.delta_clicks "click_view_gclid" "segments_date"
fi
if bestaat "${BRON}/google_ads/ads_Campaign_${ADS_ID}.ndjson.gz"; then
  laad_delta raw_ads.delta_campaign "${BRON}/google_ads/ads_Campaign_${ADS_ID}.ndjson.gz" ads_Campaign --source_format=NEWLINE_DELIMITED_JSON
  voeg_samen "raw_ads.ads_Campaign_${ADS_ID}" raw_ads.delta_campaign \
    "CONCAT(CAST(campaign_id AS STRING), '|', CAST(_DATA_DATE AS STRING))" "_DATA_DATE"
fi

echo "== Meta Ads =="
META="${BRON}/meta/meta_ad_insights_${DAG//-/}.csv"
if bestaat "${META}"; then
  laad_delta raw_ads.delta_meta "${META}" meta_ad_insights --source_format=CSV --skip_leading_rows=1
  voeg_samen raw_ads.meta_ad_insights raw_ads.delta_meta "CONCAT(campaign_id, '|', CAST(date_start AS STRING))" "clicks"
fi

echo "== E-mailplatform =="
if bestaat "${BRON}/email/"; then
  laad_delta raw_email.delta_events "${BRON}/email/events_*.ndjson.gz" email_events --source_format=NEWLINE_DELIMITED_JSON
  voeg_samen raw_email.events raw_email.delta_events "JSON_VALUE(payload, '\$.id')" "dwh_geladen_op"
fi

echo "== Leveranciers =="
if bestaat "${BRON}/leveranciers/noorderlicht/"; then
  bq -q --location="${LOC}" load --noreplace --source_format=CSV --skip_leading_rows=1 --field_delimiter=';' \
    "${PROJECT}:raw.prijzen_noorderlicht" "${BRON}/leveranciers/noorderlicht/*.csv" "${SCHEMA}/prijzen_noorderlicht.json"
  echo "   raw.prijzen_noorderlicht (nieuwe prijslijst toegevoegd)"
fi
if bestaat "${BRON}/leveranciers/houtheem/"; then
  bq -q --location="${LOC}" load --noreplace --source_format=CSV --skip_leading_rows=1 --field_delimiter=';' \
    --encoding=ISO-8859-1 --allow_jagged_rows \
    "${PROJECT}:raw.prijzen_houtheem" "${BRON}/leveranciers/houtheem/*.csv" "${SCHEMA}/prijzen_houtheem.json"
  echo "   raw.prijzen_houtheem (nieuwe prijslijst toegevoegd)"
fi

echo "Levering ${DAG} verwerkt."
