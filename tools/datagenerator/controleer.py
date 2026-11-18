#!/usr/bin/env python3
"""
Controleert de gegenereerde data vóórdat je die uploadt.

    python3 controleer.py --uitvoer data

Toont per bron het volume en controleert of de bronnen op elkaar aansluiten:
orders terug te vinden in GA4, Google Ads-kliks terug te vinden in GA4, leveranciersprijzen voor elk product.
Gebruikt de antwoordsleutel (data/_antwoordsleutel) om omzet, marge en kosten per kanaal te tonen:
zo weet je straks of je warehouse dezelfde cijfers oplevert.
"""
import argparse
import csv
import glob
import gzip
import json
import os
from collections import Counter, defaultdict


def lees(pad):
    with gzip.open(pad, "rt", encoding="utf-8") as f:
        for regel in f:
            if regel.strip():
                yield json.loads(regel)


def kop(t):
    print(f"\n{t}\n{'-' * len(t)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uitvoer", default="data")
    a = ap.parse_args()
    basis = os.path.expanduser(a.uitvoer)
    bf = os.path.join(basis, "backfill")
    if not os.path.isdir(bf):
        raise SystemExit(f"Map {bf} niet gevonden. Draai eerst: python3 genereer.py --uitvoer {a.uitvoer}")
    fouten = []

    # ------------------------------------------------------------------ webshop
    kop("1. Webshop (backfill, stand 31-10-2026)")
    klanten = list(lees(os.path.join(bf, "webshop", "klanten.ndjson.gz")))
    orders = list(lees(os.path.join(bf, "webshop", "orders.ndjson.gz")))
    regels = list(lees(os.path.join(bf, "webshop", "orderregels.ndjson.gz")))
    producten = list(lees(os.path.join(bf, "webshop", "producten.ndjson.gz")))
    print(f"klanten: {len(klanten):,}   orders: {len(orders):,}   orderregels: {len(regels):,}   productversies: {len(producten):,} "
          f"({len({p['product_id'] for p in producten})} producten)")
    statussen = Counter(o["status"] for o in orders)
    print("statussen:", dict(statussen.most_common()))
    per_maand = Counter(o["besteld_op"][:7] for o in orders if not o["is_testorder"])
    maanden = sorted(per_maand)
    print("orders per maand:", "  ".join(f"{m[2:]}: {per_maand[m]}" for m in maanden))
    emails = Counter(k["email"].strip().lower() for k in klanten)
    dubbel = sum(1 for e, n in emails.items() if n > 1)
    print(f"e-mailadressen met meer dan één klant_id (gasten die terugkomen): {dubbel:,}")
    regel_orders = {r["order_id"] for r in regels}
    zonder = [o for o in orders if o["order_id"] not in regel_orders]
    if zonder:
        fouten.append(f"{len(zonder)} orders zonder orderregels")

    # ------------------------------------------------------------------ antwoordsleutel
    sleutel = {s["order_id"]: s for s in lees(os.path.join(basis, "_antwoordsleutel", "orders_waarheid.ndjson.gz"))}
    eind_status = {o["order_id"]: o["status"] for o in orders}

    # ------------------------------------------------------------------ GA4
    kop("2. GA4-export (backfill)")
    bestanden = sorted(glob.glob(os.path.join(bf, "ga4", "events_*.ndjson.gz")))
    tids, gclids, sessies, events = Counter(), set(), 0, 0
    for pad in bestanden:
        with gzip.open(pad, "rt", encoding="utf-8") as f:
            for regel in f:
                events += 1
                if '"event_name":"purchase"' in regel:
                    e = json.loads(regel)
                    tids[e["ecommerce"]["transaction_id"]] += 1
                elif '"event_name":"session_start"' in regel:
                    sessies += 1
                    if '"gclid":"' in regel:
                        e = json.loads(regel)
                        gclids.add(e["collected_traffic_source"]["gclid"])
    print(f"dagbestanden: {len(bestanden)}   events: {events:,}   sessies: {sessies:,}   purchase-events: {sum(tids.values()):,}")
    order_ids = {str(o["order_id"]) for o in orders if not o["is_testorder"]}
    letterlijk = sum(1 for t in tids if t in order_ids)
    zonder_prefix = {t.replace("MV-", "") for t in tids}
    gevonden = sum(1 for oid in order_ids if oid in zonder_prefix)
    print(f"orders letterlijk terug in GA4 (transaction_id = order_id): {letterlijk / len(order_ids):.1%}")
    print(f"orders terug in GA4 na opschonen (zonder 'MV-'):           {gevonden / len(order_ids):.1%}   (verwacht ± 90%)")
    print(f"transaction_ids die vaker dan één keer voorkomen:          {sum(1 for n in tids.values() if n > 1):,}")
    if not 0.85 <= gevonden / len(order_ids) <= 0.95:
        fouten.append("GA4-koppelpercentage buiten 85-95%")

    # ------------------------------------------------------------------ Google Ads
    kop("3. Google Ads (DTS-formaat)")
    g = os.path.join(bf, "google_ads")
    stats = list(lees(glob.glob(os.path.join(g, "ads_CampaignBasicStats_*.ndjson.gz"))[0]))
    kliks = list(lees(glob.glob(os.path.join(g, "ads_ClickStats_*.ndjson.gz"))[0]))
    camp = list(lees(glob.glob(os.path.join(g, "ads_Campaign_*.ndjson.gz"))[0]))
    kosten_g = defaultdict(float)
    for r in stats:
        kosten_g[r["segments_date"][:7]] += r["metrics_cost_micros"] / 1e6
    gklik = {r["click_view_gclid"] for r in kliks}
    print(f"campagnes: {len({c['campaign_id'] for c in camp})}   statistiekrijen: {len(stats):,}   kliks (ClickStats): {len(kliks):,}")
    print(f"GA4-gclids terug te vinden in ClickStats: {len(gclids & gklik) / max(len(gclids), 1):.1%}   (verwacht 100%)")
    if gclids and len(gclids & gklik) / len(gclids) < 0.99:
        fouten.append("gclids uit GA4 ontbreken in ClickStats")

    # ------------------------------------------------------------------ Meta
    kop("4. Meta Ads")
    kosten_m = defaultdict(float)
    with open(os.path.join(bf, "meta", "meta_ad_insights.csv"), encoding="utf-8") as f:
        mrijen = list(csv.DictReader(f))
    for r in mrijen:
        kosten_m[r["date_start"][:7]] += float(r["spend"])
    print(f"rijen: {len(mrijen):,}   campagnes: {len({r['campaign_id'] for r in mrijen})}")

    # ------------------------------------------------------------------ e-mail
    kop("5. E-mailplatform")
    types = Counter()
    for pad in glob.glob(os.path.join(bf, "email", "*.ndjson.gz")):
        for r in lees(pad):
            types[r["payload"]["metric"]] += 1
    print("events:", dict(types.most_common()))

    # ------------------------------------------------------------------ leveranciers
    kop("6. Leveranciers")
    skus = {p["sku"] for p in producten}
    gedekt = set()
    for pad in glob.glob(os.path.join(bf, "leveranciers", "noorderlicht", "*.csv")):
        with open(pad, encoding="utf-8") as f:
            gedekt |= {r["artikelnummer"] for r in csv.DictReader(f, delimiter=";")}
    for pad in glob.glob(os.path.join(bf, "leveranciers", "houtheem", "*.csv")):
        with open(pad, encoding="cp1252") as f:
            gedekt |= {r["Artikelcode"].upper() for r in csv.DictReader(f, delimiter=";")}
    nl = len(glob.glob(os.path.join(bf, "leveranciers", "noorderlicht", "*.csv")))
    hh = len(glob.glob(os.path.join(bf, "leveranciers", "houtheem", "*.csv")))
    print(f"bestanden Noorderlicht: {nl}   Hout & Heem: {hh}   producten met een inkoopprijs: {len(skus & gedekt) / len(skus):.1%}")
    if len(skus & gedekt) / len(skus) < 0.97:
        fouten.append("niet alle producten hebben een inkoopprijs")

    # ------------------------------------------------------------------ waarheid per kanaal
    kop("7. Zo zou je warehouse moeten uitkomen (antwoordsleutel, niet-geannuleerde orders, jan 2025 - okt 2026)")
    per_kanaal = defaultdict(lambda: [0, 0.0, 0.0])
    for oid, s in sleutel.items():
        if s["besteld_op"] > "2026-10-31T23" or s["is_testorder"] or eind_status.get(oid, s["status_eind"]) in ("cancelled", "canceled"):
            continue
        k = per_kanaal[s["echt_kanaal"]]
        k[0] += 1
        k[1] += s["omzet_excl_btw"]
        k[2] += s["omzet_excl_btw"] - s["inkoopwaarde"]
    tot_g, tot_m = sum(kosten_g.values()), sum(kosten_m.values())
    print(f"{'kanaal':<12}{'orders':>8}{'omzet excl btw':>17}{'brutomarge':>13}{'kosten':>11}{'ROAS':>7}{'POAS':>7}")
    for kanaal, (n, omzet, marge) in sorted(per_kanaal.items(), key=lambda x: -x[1][1]):
        kosten = tot_g if kanaal == "google_ads" else (tot_m if kanaal == "meta_ads" else 0)
        roas = f"{omzet / kosten:.1f}" if kosten else "-"
        poas = f"{marge / kosten:.2f}" if kosten else "-"
        print(f"{kanaal:<12}{n:>8,}{omzet:>17,.0f}{marge:>13,.0f}{kosten:>11,.0f}{roas:>7}{poas:>7}")
    totaal_omzet = sum(v[1] for v in per_kanaal.values())
    print(f"{'totaal':<12}{sum(v[0] for v in per_kanaal.values()):>8,}{totaal_omzet:>17,.0f}"
          f"{sum(v[2] for v in per_kanaal.values()):>13,.0f}{tot_g + tot_m:>11,.0f}")
    print("Let op: 'echt_kanaal' is de waarheid uit de simulatie. In je warehouse zie je minder, omdat ± 10% van de\n"
          "orders geen GA4-sessie heeft (consent, telefoon) en daar het kanaal 'Onbekend' krijgt.")

    # ------------------------------------------------------------------ dagelijkse leveringen
    kop("8. Dagelijkse leveringen (november 2026)")
    dagen = sorted(os.listdir(os.path.join(basis, "dagelijks"))) if os.path.isdir(os.path.join(basis, "dagelijks")) else []
    print(f"leveringen: {len(dagen)} ({dagen[0] if dagen else '-'} t/m {dagen[-1] if dagen else '-'})")

    kop("Resultaat")
    if fouten:
        for f in fouten:
            print("FOUT:", f)
        raise SystemExit(1)
    print("Alles klopt. Volgende stap: een bucket maken en uploaden (README.md, stap 5 en 6).")


if __name__ == "__main__":
    main()
