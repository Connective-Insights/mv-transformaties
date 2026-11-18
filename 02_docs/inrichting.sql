-- Brons: de bestaande datasets een beschrijving en labels geven
ALTER SCHEMA `mv-dwh-marktvizier-tb.raw_webshop` SET OPTIONS (
  description = 'Brons: webshopdatabase (gesimuleerd; in het doelbeeld Datastream). Niet wijzigen.',
  labels = [('laag', 'brons'), ('bron', 'webshop')]
);
ALTER SCHEMA `mv-dwh-marktvizier-tb.analytics_123456789` SET OPTIONS (
  description = 'Brons: GA4-export, één tabel per dag (events_JJJJMMDD). Niet wijzigen.',
  labels = [('laag', 'brons'), ('bron', 'ga4')]
);
ALTER SCHEMA `mv-dwh-marktvizier-tb.raw_ads` SET OPTIONS (
  description = 'Brons: Google Ads (DTS-formaat) en Meta Ads. Niet wijzigen.',
  labels = [('laag', 'brons'), ('bron', 'ads')]
);
ALTER SCHEMA `mv-dwh-marktvizier-tb.raw_email` SET OPTIONS (
  description = 'Brons: e-mailplatform, volledige API-payload als JSON. Niet wijzigen.',
  labels = [('laag', 'brons'), ('bron', 'email')]
);
ALTER SCHEMA `mv-dwh-marktvizier-tb.raw` SET OPTIONS (
  description = 'Brons: prijslijsten van leveranciers (CSV). Niet wijzigen.',
  labels = [('laag', 'brons'), ('bron', 'leveranciers')]
);
 
-- Zilver, goud en assertions: de datasets voor de geplande run
CREATE SCHEMA IF NOT EXISTS `mv-dwh-marktvizier-tb.staging`
OPTIONS (location = 'EU',
  description = 'Zilver: opgeschoonde, ontdubbelde en getypeerde brondata (Dataform).',
  labels = [('laag', 'zilver')]);
CREATE SCHEMA IF NOT EXISTS `mv-dwh-marktvizier-tb.marts`
OPTIONS (location = 'EU',
  description = 'Goud: sterschema en rapporttabellen. Bron voor alle dashboards.',
  labels = [('laag', 'goud')]);
CREATE SCHEMA IF NOT EXISTS `mv-dwh-marktvizier-tb.dataform_assertions`
OPTIONS (location = 'EU',
  description = 'Resultaten van Dataform-assertions.',
  labels = [('laag', 'test')]);
 
-- Ontwikkelen: dezelfde datasets met achtervoegsel _dev (workspace compilation overrides);
-- tabellen verdwijnen na 14 dagen vanzelf, zodat oude proefversies niets blijven kosten
CREATE SCHEMA IF NOT EXISTS `mv-dwh-marktvizier-tb.staging_dev`
OPTIONS (location = 'EU', default_table_expiration_days = 14, labels = [('laag', 'dev')]);
CREATE SCHEMA IF NOT EXISTS `mv-dwh-marktvizier-tb.marts_dev`
OPTIONS (location = 'EU', default_table_expiration_days = 14, labels = [('laag', 'dev')]);
CREATE SCHEMA IF NOT EXISTS `mv-dwh-marktvizier-tb.dataform_assertions_dev`
OPTIONS (location = 'EU', default_table_expiration_days = 14, labels = [('laag', 'dev')]);

Rechten op de data geeft u per dataset, met SQL:
-- Het lukte mij niet om alle SQL statements als bulk te draaien, dus heb ik het handmatig een voor een gedaan. Er moet echter een manier zijn om dezelfde statements als bulk te draaien.
-- Brons: alleen lezen
GRANT `roles/bigquery.dataViewer` ON SCHEMA `mv-dwh-marktvizier-tb.raw_webshop`
  TO "serviceAccount:sa-dataform@mv-dwh-marktvizier-tb.iam.gserviceaccount.com";
GRANT `roles/bigquery.dataViewer` ON SCHEMA `mv-dwh-marktvizier-tb.analytics_123456789`
  TO "serviceAccount:sa-dataform@mv-dwh-marktvizier-tb.iam.gserviceaccount.com";
GRANT `roles/bigquery.dataViewer` ON SCHEMA `mv-dwh-marktvizier-tb.raw_ads`
  TO "serviceAccount:sa-dataform@mv-dwh-marktvizier-tb.iam.gserviceaccount.com";
GRANT `roles/bigquery.dataViewer` ON SCHEMA `mv-dwh-marktvizier-tb.raw_email`
  TO "serviceAccount:sa-dataform@mv-dwh-marktvizier-tb.iam.gserviceaccount.com";
GRANT `roles/bigquery.dataViewer` ON SCHEMA `mv-dwh-marktvizier-tb.raw`
  TO "serviceAccount:sa-dataform@mv-dwh-marktvizier-tb.iam.gserviceaccount.com";
 
-- Zilver, goud en assertions, zowel de geplande als de _dev-variant: schrijven
GRANT `roles/bigquery.dataEditor` ON SCHEMA `mv-dwh-marktvizier-tb.staging`
  TO "serviceAccount:sa-dataform@mv-dwh-marktvizier-tb.iam.gserviceaccount.com";
GRANT `roles/bigquery.dataEditor` ON SCHEMA `mv-dwh-marktvizier-tb.marts`
  TO "serviceAccount:sa-dataform@mv-dwh-marktvizier-tb.iam.gserviceaccount.com";
GRANT `roles/bigquery.dataEditor` ON SCHEMA `mv-dwh-marktvizier-tb.dataform_assertions`
  TO "serviceAccount:sa-dataform@mv-dwh-marktvizier-tb.iam.gserviceaccount.com";
GRANT `roles/bigquery.dataEditor` ON SCHEMA `mv-dwh-marktvizier-tb.staging_dev`
  TO "serviceAccount:sa-dataform@mv-dwh-marktvizier-tb.iam.gserviceaccount.com";
GRANT `roles/bigquery.dataEditor` ON SCHEMA `mv-dwh-marktvizier-tb.marts_dev`
  TO "serviceAccount:sa-dataform@mv-dwh-marktvizier-tb.iam.gserviceaccount.com";
GRANT `roles/bigquery.dataEditor` ON SCHEMA `mv-dwh-marktvizier-tb.dataform_assertions_dev`
  TO "serviceAccount:sa-dataform@mv-dwh-marktvizier-tb.iam.gserviceaccount.com";





