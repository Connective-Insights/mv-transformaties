#!/usr/bin/env python3
"""
MarktVizier-datagenerator
=========================

Maakt samenhangende, bewust vervuilde oefendata voor een e-commerce data warehouse:
webshopdatabase, GA4-export, Google Ads (DTS), Meta Ads, e-mailplatform en twee leveranciers.

Alle bronnen delen dezelfde werkelijkheid: een order in de webshop heeft (meestal) een GA4-sessie
met dezelfde transaction_id, die sessie komt uit een campagne waarvan de kosten in Google Ads of
Meta staan, en de klant krijgt e-mails op hetzelfde (rommelig ingevoerde) e-mailadres.

Gebruik (Python 3.9 of hoger, geen extra pakketten nodig):

    python3 genereer.py                       # standaard: jan 2025 t/m nov 2026, map ./data
    python3 genereer.py --schaal 0.25         # snelle proefrun met een kwart van het volume
    python3 genereer.py --uitvoer ~/mv_data   # andere uitvoermap

Uitvoer:
    data/backfill/...            stand per 31 oktober 2026 (de historische eerste lading)
    data/dagelijks/JJJJ-MM-DD/   wat er die dag binnenkomt (1 t/m 30 november 2026)

Zelfde --seed = exact dezelfde data. Zie README.md voor het stappenplan.
"""
import argparse
import csv
import gzip
import io
import json
import math
import os
import random
import re
import sys
import time
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    AMS = ZoneInfo("Europe/Amsterdam")
except Exception:  # zeer oude Python: val terug op vaste offset (alleen voor de tijdzonevervuiling)
    AMS = timezone(timedelta(hours=1))
UTC = timezone.utc

# ----------------------------------------------------------------------------------------------
# Instellingen. Pas gerust aan; alles is relatief ten opzichte van --schaal.
# ----------------------------------------------------------------------------------------------
CONFIG = {
    "start": date(2025, 1, 1),
    "eind": date(2026, 11, 30),
    "backfill_tot": date(2026, 10, 31),          # laatste dag in de historische lading
    "sessies_per_dag": 1750,                      # niet-e-mailsessies per gemiddelde dag in 2025
    "groei_per_jaar": 0.16,
    "ga4_property_id": "123456789",
    "ga4_stream_id": "4567890123",
    "google_ads_klant_id": "1234567890",
    "meta_account_id": "act_801234567890123",
    "site": "https://www.marktvizier.example",
}

# kanaalaandeel van de niet-e-mailsessies en de kans dat een sessie converteert
KANALEN = {
    "organisch":  {"aandeel": 0.30, "conversie": 0.027, "nieuw": 0.82},
    "google_ads": {"aandeel": 0.30, "conversie": None,  "nieuw": None},   # per campagne
    "direct":     {"aandeel": 0.17, "conversie": 0.040, "nieuw": 0.55},
    "meta_ads":   {"aandeel": 0.13, "conversie": None,  "nieuw": None},   # per campagne
    "social":     {"aandeel": 0.05, "conversie": 0.010, "nieuw": 0.88},
    "verwijzing": {"aandeel": 0.05, "conversie": 0.022, "nieuw": 0.85},
}

GOOGLE_CAMPAGNES = [
    {"id": 20145601231, "naam": "Search | Merk | NL", "type": "SEARCH", "gewicht": 0.17, "conv": 0.075, "cpc": 0.45, "ctr": 0.14, "nieuw": 0.50},
    {"id": 20145601877, "naam": "Search | Generiek | Duurzaam wonen", "type": "SEARCH", "gewicht": 0.22, "conv": 0.011, "cpc": 1.15, "ctr": 0.045, "nieuw": 0.92},
    {"id": 20145602410, "naam": "Shopping | Bestsellers", "type": "SHOPPING", "gewicht": 0.31, "conv": 0.031, "cpc": 0.68, "ctr": 0.012, "nieuw": 0.78, "bestsellers": True},
    {"id": 20145602995, "naam": "PMax | Algemeen", "type": "PERFORMANCE_MAX", "gewicht": 0.22, "conv": 0.021, "cpc": 0.74, "ctr": 0.018, "nieuw": 0.82,
     "hernoemd": (date(2026, 2, 1), "PMax | Alle producten")},
    {"id": 20145603318, "naam": "Shopping | Tuin seizoen", "type": "SHOPPING", "gewicht": 0.10, "conv": 0.024, "cpc": 0.72, "ctr": 0.011, "nieuw": 0.85,
     "maanden": {3, 4, 5, 6, 7, 8}, "categorie": "Tuin"},
    {"id": 20145604102, "naam": "Search | Black Friday", "type": "SEARCH", "gewicht": 0.30, "conv": 0.048, "cpc": 0.85, "ctr": 0.06, "nieuw": 0.70,
     "bf": True},
]
META_CAMPAGNES = [
    {"id": "120208765432100011", "naam": "Prospecting | Lookalike kopers", "gewicht": 0.34, "conv": 0.0065, "cpc": 0.48, "ctr": 0.011, "nieuw": 0.95},
    {"id": "120208765432100027", "naam": "Prospecting | Interesse duurzaam wonen", "gewicht": 0.26, "conv": 0.0045, "cpc": 0.57, "ctr": 0.009, "nieuw": 0.96},
    {"id": "120208765432100035", "naam": "Retargeting | Winkelwagen 7d", "gewicht": 0.22, "conv": 0.034, "cpc": 0.81, "ctr": 0.021, "nieuw": 0.25},
    {"id": "120208765432100049", "naam": "Retargeting | Bestaande klanten", "gewicht": 0.18, "conv": 0.026, "cpc": 0.69, "ctr": 0.017, "nieuw": 0.05},
    {"id": "120208765432100058", "naam": "Black Friday | Alle doelgroepen", "gewicht": 0.40, "conv": 0.019, "cpc": 0.57, "ctr": 0.016, "nieuw": 0.60, "bf": True},
]

MAAND_SEIZOEN = {1: 1.05, 2: 0.90, 3: 1.00, 4: 1.00, 5: 0.95, 6: 0.86, 7: 0.80, 8: 0.85, 9: 1.00, 10: 1.05, 11: 1.22, 12: 1.15}
WEEKDAG = [1.08, 1.03, 1.00, 1.00, 0.90, 0.88, 1.12]  # ma..zo
UUR_GEWICHT = [0.6, 0.35, 0.2, 0.15, 0.15, 0.25, 0.6, 1.2, 1.9, 2.3, 2.5, 2.6, 2.7, 2.6, 2.5, 2.6, 2.8, 3.0, 3.3, 3.9, 4.4, 4.5, 3.6, 1.8]

VOORNAMEN = ["Jan", "Sanne", "Daan", "Emma", "Lucas", "Julia", "Sem", "Lotte", "Thijs", "Fleur", "Bram", "Anouk", "Ruben", "Lisa",
             "Jesse", "Eva", "Tim", "Iris", "Niels", "Sophie", "Kees", "Marieke", "Joost", "Femke", "Pieter", "Noor", "Mark", "Esther",
             "Bas", "Linda", "Wouter", "Inge", "Gijs", "Maaike", "Rik", "Hanneke", "Thomas", "Yara", "Mohamed", "Fatima", "Ahmed",
             "Sara", "Youssef", "Amira", "Lars", "Mila", "Finn", "Zoë", "Stijn", "Elif", "Koen", "Lieke", "Hugo", "Romy", "Dirk", "Ilse"]
ACHTERNAMEN = ["de Vries", "Jansen", "van den Berg", "Bakker", "Visser", "Smit", "Meijer", "de Boer", "Mulder", "de Groot", "Bos",
               "Vos", "Peters", "Hendriks", "van Leeuwen", "Dekker", "Brouwer", "de Wit", "Dijkstra", "Smits", "de Graaf", "van der Meer",
               "van der Linden", "Kok", "Jacobs", "de Haan", "Vermeulen", "van den Heuvel", "van der Veen", "van den Broek", "de Bruijn",
               "Schouten", "Willems", "van Dijk", "Hoekstra", "Maas", "Verhoeven", "Koster", "Prins", "Yilmaz", "El Amrani", "Kaya",
               "Bouzid", "Huisman", "Peeters", "Claes", "Wouters", "Goossens"]
# plaats, provincie, postcode van, postcode tot, land, gewicht
PLAATSEN = [
    ("Amsterdam", "Noord-Holland", 1011, 1109, "NL", 9), ("Rotterdam", "Zuid-Holland", 3011, 3089, "NL", 6),
    ("Den Haag", "Zuid-Holland", 2491, 2597, "NL", 5), ("Utrecht", "Utrecht", 3511, 3585, "NL", 6),
    ("Eindhoven", "Noord-Brabant", 5611, 5658, "NL", 3), ("Groningen", "Groningen", 9711, 9747, "NL", 3),
    ("Tilburg", "Noord-Brabant", 5011, 5049, "NL", 2), ("Almere", "Flevoland", 1311, 1364, "NL", 2),
    ("Breda", "Noord-Brabant", 4811, 4841, "NL", 2), ("Nijmegen", "Gelderland", 6511, 6546, "NL", 3),
    ("Apeldoorn", "Gelderland", 7311, 7339, "NL", 2), ("Haarlem", "Noord-Holland", 2011, 2037, "NL", 3),
    ("Arnhem", "Gelderland", 6811, 6846, "NL", 2), ("Enschede", "Overijssel", 7511, 7548, "NL", 2),
    ("Amersfoort", "Utrecht", 3811, 3829, "NL", 2), ("Zwolle", "Overijssel", 8011, 8043, "NL", 2),
    ("Leiden", "Zuid-Holland", 2311, 2334, "NL", 2), ("Maastricht", "Limburg", 6211, 6229, "NL", 1),
    ("Dordrecht", "Zuid-Holland", 3311, 3329, "NL", 1), ("Leeuwarden", "Friesland", 8911, 8939, "NL", 1),
    ("'s-Hertogenbosch", "Noord-Brabant", 5211, 5237, "NL", 2), ("Zoetermeer", "Zuid-Holland", 2711, 2729, "NL", 1),
    ("Deventer", "Overijssel", 7411, 7429, "NL", 1), ("Delft", "Zuid-Holland", 2611, 2629, "NL", 1),
    ("Alkmaar", "Noord-Holland", 1811, 1825, "NL", 1), ("Venlo", "Limburg", 5911, 5935, "NL", 1),
    ("Assen", "Drenthe", 9401, 9411, "NL", 1), ("Middelburg", "Zeeland", 4331, 4339, "NL", 1),
    ("Hilversum", "Noord-Holland", 1211, 1223, "NL", 1), ("Lelystad", "Flevoland", 8211, 8245, "NL", 1),
    ("Wageningen", "Gelderland", 6701, 6709, "NL", 1), ("Emmen", "Drenthe", 7811, 7833, "NL", 1),
    ("Antwerpen", "Antwerpen", 2000, 2660, "BE", 3), ("Gent", "Oost-Vlaanderen", 9000, 9052, "BE", 2),
    ("Brussel", "Brussel", 1000, 1210, "BE", 1), ("Leuven", "Vlaams-Brabant", 3000, 3012, "BE", 1),
]
PLAATS_CUM = [sum(p[5] for p in PLAATSEN[: i + 1]) for i in range(len(PLAATSEN))]
UUR_CUM = [sum(UUR_GEWICHT[: i + 1]) for i in range(24)]
LETTERS = "ABCDEFGHJKLMNPRSTVWXZ"
EMAILDOMEINEN = ["example.com", "example.net", "example.org"]   # gereserveerde domeinen: nooit echte adressen

CATALOGUS = {
    "Textiel":     {"lev": "noorderlicht", "merken": ["Noorderlicht", "Zacht & Zo"], "prijs": (19, 129), "aantal": 70,
                    "items": ["Plaid", "Kussenhoes", "Tafelkleed", "Gordijn", "Vloerkleed", "Theedoekenset", "Placemats (4)"],
                    "materiaal": ["linnen", "bio-katoen", "wol", "gerecycled katoen", "hennep"]},
    "Slapen":      {"lev": "noorderlicht", "merken": ["Noorderlicht", "Zacht & Zo"], "prijs": (35, 349), "aantal": 60,
                    "items": ["Dekbedovertrek", "Hoeslaken", "Hoofdkussen", "Dekbed", "Matrastopper", "Kussensloop (2)"],
                    "materiaal": ["bamboe", "bio-katoen", "linnen", "wol", "Tencel"]},
    "Badkamer":    {"lev": "noorderlicht", "merken": ["Noorderlicht"], "prijs": (9, 89), "aantal": 40,
                    "items": ["Handdoek", "Badmat", "Badjas", "Gastendoekjes (3)", "Douchegordijn"],
                    "materiaal": ["bio-katoen", "linnen", "bamboe"]},
    "Wonen":       {"lev": "houtheem", "merken": ["Hout & Heem"], "prijs": (29, 899), "aantal": 90,
                    "items": ["Bijzettafel", "Wandplank", "Boekenkast", "Salontafel", "Opbergmand", "Spiegel", "Krukje", "Café-tafel"],
                    "materiaal": ["eiken", "mangohout", "teak FSC", "bamboe", "rotan", "gerecycled hout"]},
    "Keuken":      {"lev": "houtheem", "merken": ["Hout & Heem"], "prijs": (9, 79), "aantal": 60,
                    "items": ["Snijplank", "Broodtrommel", "Kruidenrek", "Serveerplank", "Pollepelset", "Vershouddoeken (3)"],
                    "materiaal": ["eiken", "olijfhout", "bamboe", "bijenwas", "beuken"]},
    "Tuin":        {"lev": "houtheem", "merken": ["Groenkracht"], "prijs": (12, 399), "aantal": 50,
                    "items": ["Plantenbak", "Tuinbank", "Vogelhuisje", "Kruidenplanten (set)", "Insectenhotel", "Composter"],
                    "materiaal": ["douglas", "gerecycled kunststof", "lariks", "terracotta"]},
    "Verlichting": {"lev": "houtheem", "merken": ["Lumen Verde"], "prijs": (25, 249), "aantal": 50,
                    "items": ["Hanglamp", "Tafellamp", "Vloerlamp", "Lichtsnoer", "Wandlamp"],
                    "materiaal": ["rotan", "glas", "keramiek", "jute", "eiken"]},
}
KLEUREN = ["naturel", "zand", "olijfgroen", "antraciet", "terra", "crème", "écru", "oker", "salie", "nachtblauw"]
LABELS = ["FSC", "GOTS", "Fairtrade", "OEKO-TEX", "EU Ecolabel", None, None]

NIEUWSBRIEF_THEMAS = ["Lente in huis", "Slapen als een roos", "Nieuw binnen", "Tuinseizoen", "Zomerse tafel", "Duurzaam koken",
                      "Back to school", "Herfstgevoel", "Warme plaids", "Black Friday preview", "Cadeautips", "Wintersfeer",
                      "Nieuwjaarsdeals", "Opruimen met stijl", "Licht in donkere dagen", "Badkamer opfrissen"]

# ----------------------------------------------------------------------------------------------
# Hulpfuncties
# ----------------------------------------------------------------------------------------------
R = random.Random()


def ruuid():
    return str(uuid.UUID(int=R.getrandbits(128), version=4))


def lokaal_naar_utc(d, uur_float):
    h = int(uur_float)
    m = int((uur_float - h) * 60)
    s = R.randint(0, 59)
    return datetime(d.year, d.month, d.day, h, m, s, tzinfo=AMS).astimezone(UTC)


def iso(ts):
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ms(ts):
    return int(ts.timestamp() * 1000)


def us(ts):
    return int(ts.timestamp() * 1_000_000)


def lokale_datum(ts):
    return ts.astimezone(AMS).date()


def gewogen(keuzes, gewichten):
    return R.choices(keuzes, weights=gewichten, k=1)[0]


def slug(tekst):
    t = tekst.lower().replace("&", "en").replace("|", " ")
    t = re.sub(r"[^a-z0-9]+", "_", t)
    return t.strip("_")


def poisson(lam):
    if lam <= 0:
        return 0
    if lam > 60:
        return max(0, int(round(R.gauss(lam, math.sqrt(lam)))))
    l, k, p = math.exp(-lam), 0, 1.0
    while True:
        k += 1
        p *= R.random()
        if p <= l:
            return k - 1


def black_friday(jaar):
    d = date(jaar, 11, 1)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d + timedelta(days=21)


def bf_factor(d):
    bf = black_friday(d.year)
    if d == bf:
        return 2.6, 1.45
    if d == bf + timedelta(days=3):          # cyber monday
        return 1.8, 1.30
    if bf - timedelta(days=6) <= d <= bf + timedelta(days=3):
        return 1.45, 1.25
    if bf - timedelta(days=14) <= d < bf - timedelta(days=6):
        return 0.92, 0.85                    # klanten wachten op de actie
    if d.month == 12 and d.day >= 24:
        return 0.6, 0.9
    return 1.0, 1.0


def in_bf_periode(d):
    bf = black_friday(d.year)
    return bf - timedelta(days=10) <= d <= bf + timedelta(days=3)


def euro(x):
    return round(x + 1e-9, 2)


# ----------------------------------------------------------------------------------------------
# Schrijvers
# ----------------------------------------------------------------------------------------------
class Uitvoer:
    def __init__(self, map_):
        self.map = map_

    def pad(self, *delen):
        p = os.path.join(self.map, *delen)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def ndjson(self, rijen, *delen):
        if not rijen and delen and delen[0] == "dagelijks":
            return   # geen lege bestanden in de dagelijkse leveringen
        with gzip.open(self.pad(*delen), "wt", encoding="utf-8", compresslevel=5) as f:
            for r in rijen:
                f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
                f.write("\n")

    def ndjson_regels(self, regels, *delen):
        if not regels and delen and delen[0] == "dagelijks":
            return
        with gzip.open(self.pad(*delen), "wt", encoding="utf-8", compresslevel=5) as f:
            f.write("\n".join(regels))
            if regels:
                f.write("\n")

    def csvbestand(self, kop, rijen, *delen, scheiding=",", codering="utf-8"):
        if not rijen and delen and delen[0] == "dagelijks":
            return
        with open(self.pad(*delen), "w", encoding=codering, newline="", errors="replace") as f:
            w = csv.writer(f, delimiter=scheiding, lineterminator="\r\n" if codering != "utf-8" else "\n")
            w.writerow(kop)
            w.writerows(rijen)


# ----------------------------------------------------------------------------------------------
# De gesimuleerde wereld
# ----------------------------------------------------------------------------------------------
class Wereld:
    def __init__(self, schaal, uit):
        self.schaal = schaal
        self.uit = uit
        self.producten = []                 # dicts met versies
        self.product_versies = []           # (ts, rij) append-only
        self.inkoop = {}                    # sku -> [(geldig_vanaf, prijs)]
        self.klanten = {}                   # klant_id -> dict
        self.klant_versies = []             # (ts, rij)
        self.orders = []                    # dicts
        self.order_versies = []             # (ts, rij)
        self.regels = []                    # (ts, rij)
        self.volgende_klant = 100001
        self.volgende_order = 5000001
        self.gepland = defaultdict(list)    # datum -> [klant_id] (herhaalaankoop-intenties)
        self.wachtrij = []                  # klanten die vandaag/onlangs wilden kopen
        self.abonnees = {}                  # e-mail (genormaliseerd) -> dict
        self.popup_niet_klant = []          # e-mails van inschrijvers zonder order
        self.email_events = defaultdict(list)   # lokale datum -> [payload]
        self.google_stats = defaultdict(lambda: defaultdict(float))  # (datum, cid, device) -> metrics
        self.google_clicks = defaultdict(list)  # datum -> [(gclid, cid, device)]
        self.meta_stats = defaultdict(lambda: defaultdict(float))    # (datum, cid) -> metrics
        self.email_kliks = defaultdict(list)    # lokale datum -> [(ts, email, klant_id, utm)]
        self.email_bestanden = 0
        self.pool_cache = {}
        self.sku_index = {}
        self.ga4_dagen = 0
        self.ga4_events = 0
        self.ga4_backfill_paden = []
        self.pseudo_teller = 0

    # ------------------------------------------------------------------ catalogus
    def bouw_catalogus(self):
        pid = 1001
        nummer = {"noorderlicht": 10001, "houtheem": 20001}
        start = CONFIG["start"]
        for cat, c in CATALOGUS.items():
            for i in range(c["aantal"]):
                item = R.choice(c["items"])
                naam = f"{item} {R.choice(c['materiaal'])} {R.choice(KLEUREN)}"
                lev = c["lev"]
                sku = ("NL-" if lev == "noorderlicht" else "HH-") + str(nummer[lev]).zfill(5)
                nummer[lev] += R.randint(1, 7)
                lo, hi = c["prijs"]
                prijs = round(math.exp(R.uniform(math.log(lo), math.log(hi)))) - 0.05
                btw = 0.09 if "planten" in item.lower() else 0.21
                # lancering: 85% bestaat al bij de start, de rest komt gespreid binnen
                if R.random() < 0.85:
                    lancering = start - timedelta(days=R.randint(30, 900))
                else:
                    lancering = start + timedelta(days=R.randint(10, 640))
                p = {
                    "product_id": pid, "sku": sku, "productnaam": naam, "categorie": cat, "merk": R.choice(c["merken"]),
                    "duurzaamheidslabel": R.choice(LABELS), "leverancier": "Noorderlicht Textiel" if lev == "noorderlicht" else "Hout & Heem",
                    "lev": lev, "verkoopprijs_incl_btw": prijs, "btw_tarief": btw, "actief": True, "lancering": lancering,
                    "populariteit": R.paretovariate(1.3) * (40 / prijs) ** 0.9, "bestseller": False,
                }
                pid += 1
                self.producten.append(p)
                marge = R.uniform(0.38, 0.56)
                ink = round(prijs / (1 + btw) * marge, 2)
                self.inkoop[sku] = [(min(lancering, start) - timedelta(days=60), ink)]
        self.sku_index = {p["sku"]: p for p in self.producten}
        # bestsellers = top 10% populariteit
        top = sorted(self.producten, key=lambda p: -p["populariteit"])[: len(self.producten) // 10]
        for p in top:
            p["bestseller"] = True
        # eerste versie (INSERT) van elk product
        for p in self.producten:
            ts = datetime.combine(min(p["lancering"], CONFIG["start"] - timedelta(days=1)), datetime.min.time(), tzinfo=AMS).astimezone(UTC)
            p["aangemaakt_op"] = ts
            self._product_versie(p, ts, "INSERT")
        # geplande wijzigingen: prijzen, categorie, label, uitfasering
        self.product_wijzigingen = defaultdict(list)
        eind = CONFIG["eind"]
        for p in self.producten:
            d = max(p["lancering"], CONFIG["start"])
            while True:
                d = d + timedelta(days=R.randint(110, 240))
                if d > eind:
                    break
                factor = R.uniform(1.02, 1.08) if R.random() < 0.8 else R.uniform(0.94, 0.99)
                self.product_wijzigingen[d].append(("inkoop", p, factor))
                if R.random() < 0.6:   # verkoopprijs volgt soms, met vertraging
                    self.product_wijzigingen[d + timedelta(days=R.randint(5, 40))].append(("verkoop", p, factor))
            if R.random() < 0.05:
                dag = CONFIG["start"] + timedelta(days=R.randint(60, 650))
                nieuw = {"Slapen": "Textiel", "Textiel": "Wonen", "Badkamer": "Textiel", "Wonen": "Keuken", "Keuken": "Wonen",
                         "Tuin": "Wonen", "Verlichting": "Wonen"}[p["categorie"]]
                self.product_wijzigingen[dag].append(("categorie", p, nieuw))
            if R.random() < 0.04:
                self.product_wijzigingen[CONFIG["start"] + timedelta(days=R.randint(60, 650))].append(("label", p, R.choice(LABELS[:5])))
            if R.random() < 0.06:
                self.product_wijzigingen[CONFIG["start"] + timedelta(days=R.randint(200, 690))].append(("uitfaseren", p, None))

    def _product_versie(self, p, ts, soort):
        rij = {k: p[k] for k in ("product_id", "sku", "productnaam", "categorie", "merk", "duurzaamheidslabel", "leverancier",
                                 "verkoopprijs_incl_btw", "btw_tarief", "actief")}
        rij["aangemaakt_op"] = iso(p["aangemaakt_op"])
        rij["gewijzigd_op"] = iso(ts)
        rij["datastream_metadata"] = {"uuid": ruuid(), "source_timestamp": ms(ts), "change_type": soort,
                                      "change_sequence_number": f"{ms(ts):x}-{R.randint(0, 0xffff):04x}"}
        self.product_versies.append((ts, rij))

    def pas_productwijzigingen_toe(self, d):
        for soort, p, waarde in self.product_wijzigingen.get(d, []):
            ts = lokaal_naar_utc(d, R.uniform(7, 18))
            if soort == "inkoop":
                oud = self.inkoop[p["sku"]][-1][1]
                self.inkoop[p["sku"]].append((d, round(oud * waarde, 2)))
                continue
            if soort == "verkoop":
                p["verkoopprijs_incl_btw"] = round(p["verkoopprijs_incl_btw"] * waarde) - 0.05 if p["verkoopprijs_incl_btw"] > 20 \
                    else round(p["verkoopprijs_incl_btw"] * waarde, 2)
            elif soort == "categorie":
                p["categorie"] = waarde
            elif soort == "label":
                p["duurzaamheidslabel"] = waarde
            elif soort == "uitfaseren":
                p["actief"] = False
            self._product_versie(p, ts, "UPDATE")

    def actieve_producten(self, d, categorie=None, bestsellers=False):
        return self.pool(d, categorie, bestsellers)[0]

    def pool(self, d, categorie=None, bestsellers=False):
        """Actieve producten op dag d plus cumulatieve populariteitsgewichten (per dag gecachet)."""
        sleutel = (d, categorie, bestsellers)
        if sleutel not in self.pool_cache:
            if len(self.pool_cache) > 50:
                self.pool_cache.clear()
            res = [p for p in self.producten if p["actief"] and p["lancering"] <= d
                   and (categorie is None or p["categorie"] == categorie) and (not bestsellers or p["bestseller"])]
            res = res or [p for p in self.producten if p["actief"] and p["lancering"] <= d]
            cum, t = [], 0.0
            for p in res:
                t += p["populariteit"]
                cum.append(t)
            self.pool_cache[sleutel] = (res, cum)
        return self.pool_cache[sleutel]

    def inkoopprijs(self, sku, d):
        prijs = self.inkoop[sku][0][1]
        for vanaf, pr in self.inkoop[sku]:
            if vanaf <= d:
                prijs = pr
        return prijs

    # ------------------------------------------------------------------ klanten
    def maak_identiteit(self):
        vn, an = R.choice(VOORNAMEN), R.choice(ACHTERNAMEN)
        plaats = R.choices(PLAATSEN, cum_weights=PLAATS_CUM)[0]
        basis = f"{vn}.{an}".lower().replace(" ", "").replace("'", "").replace("ë", "e")
        email = f"{basis}{R.randint(1, 999)}@{R.choice(EMAILDOMEINEN)}"
        return {"voornaam": vn, "achternaam": an, "email": email, "plaats": plaats}

    @staticmethod
    def vuil_email(e):
        x = R.random()
        if x < 0.04:
            return e[0].upper() + e[1:]
        if x < 0.06:
            return " " + e
        if x < 0.08:
            return e + " "
        if x < 0.09:
            return e.upper()
        return e

    def postcode(self, plaats):
        naam, prov, lo, hi, land, _ = plaats
        cijfers = R.randint(lo, hi)
        if land == "BE":
            return str(cijfers)
        letters = R.choice(LETTERS) + R.choice(LETTERS)
        x = R.random()
        if x < 0.70:
            return f"{cijfers} {letters}"
        if x < 0.92:
            return f"{cijfers}{letters}"
        return f"{cijfers}{letters.lower()}"

    @staticmethod
    def land_waarde(land):
        if land == "BE":
            return R.choices(["BE", "België", "Belgie", "be", "BEL"], weights=[70, 12, 6, 6, 6])[0]
        return R.choices(["NL", "Nederland", "nl", "NLD", "The Netherlands", None], weights=[78, 9, 5, 3, 2, 3])[0]

    @staticmethod
    def plaatsnaam(naam):
        x = R.random()
        if naam == "Den Haag" and x < 0.15:
            return "'s-Gravenhage"
        if x < 0.03:
            return naam + " "
        if x < 0.05:
            return naam.upper()
        return naam

    def nieuwe_klant(self, ts, gast, identiteit=None):
        ident = identiteit or self.maak_identiteit()
        kid = self.volgende_klant
        self.volgende_klant += 1
        pl = ident["plaats"]
        k = {
            "klant_id": kid, "voornaam": ident["voornaam"], "achternaam": ident["achternaam"],
            "email_schoon": ident["email"], "email": self.vuil_email(ident["email"]),
            "postcode": self.postcode(pl), "plaats": self.plaatsnaam(pl[0]), "land_echt": pl[4], "land": self.land_waarde(pl[4]),
            "provincie": pl[1], "nieuwsbrief_opt_in": (R.random() < 0.42) if R.random() > 0.03 else None,
            "is_gast": gast, "aangemaakt_op": ts, "loyaliteit": R.betavariate(2, 5), "pseudo_ids": [],
            "orders": 0, "pl": pl,
        }
        self.klanten[kid] = k
        ab = self.abonnees.get(ident["email"])
        if ab is not None and ab["klant_id"] is None:
            ab["klant_id"] = kid
        self._klant_versie(k, ts)
        if k["nieuwsbrief_opt_in"]:
            self.schrijf_in(ident["email"], ts, kid, bron="checkout")
        return k

    def _klant_versie(self, k, ts):
        rij = {"klant_id": k["klant_id"], "voornaam": k["voornaam"], "achternaam": k["achternaam"], "email": k["email"],
               "postcode": k["postcode"], "plaats": k["plaats"], "land": k["land"], "nieuwsbrief_opt_in": k["nieuwsbrief_opt_in"],
               "is_gast": k["is_gast"], "aangemaakt_op": iso(k["aangemaakt_op"]), "gewijzigd_op": iso(ts),
               "datastream_metadata": {"uuid": ruuid(), "source_timestamp": ms(ts)}}
        self.klant_versies.append((ts, rij))

    def verhuis(self, d):
        # ~3% van de accountklanten per jaar verhuist
        aantal = poisson(len(self.klanten) * 0.03 / 365)
        if not aantal:
            return
        ids = list(self.klanten.keys())
        for _ in range(aantal):
            k = self.klanten[R.choice(ids)]
            if k["is_gast"]:
                continue
            pl = R.choices(PLAATSEN, cum_weights=PLAATS_CUM)[0]
            k["postcode"], k["plaats"], k["land_echt"], k["land"], k["provincie"], k["pl"] = \
                self.postcode(pl), self.plaatsnaam(pl[0]), pl[4], self.land_waarde(pl[4]), pl[1], pl
            self._klant_versie(k, lokaal_naar_utc(d, R.uniform(8, 22)))

    def pseudo_id(self, k=None):
        if k is not None and k["pseudo_ids"] and R.random() < 0.7:
            return R.choice(k["pseudo_ids"]), False
        self.pseudo_teller += 1
        pid = f"{R.randint(100000000, 2147483647)}.{1700000000 + self.pseudo_teller}"
        if k is not None:
            k["pseudo_ids"].append(pid)
        return pid, True

    # ------------------------------------------------------------------ e-mail
    def schrijf_in(self, email_schoon, ts, klant_id=None, bron="popup"):
        if email_schoon in self.abonnees and self.abonnees[email_schoon]["actief"]:
            return
        self.abonnees[email_schoon] = {"actief": True, "klant_id": klant_id, "sinds": ts}
        e = self.vuil_email(email_schoon)
        self.email_events[lokale_datum(ts)].append(self._email_event("Subscribed to List", ts, e, klant_id, None,
                                                                    {"id": "flw_welkom", "name": "Welkom | Nieuwe inschrijving"} if bron == "popup" else None,
                                                                    extra={"list": "Nieuwsbrief", "method": bron}))
        if bron == "popup":
            self.popup_niet_klant.append(email_schoon)
            # welkomstmail met kortingscode, 2 min later
            self._verstuur(email_schoon, ts + timedelta(minutes=2), None, {"id": "flw_welkom", "name": "Welkom | Nieuwe inschrijving"},
                           "welkom_10_procent")

    def _email_event(self, metric, ts, email, klant_id, campagne, flow, extra=None):
        lokaal = ts.astimezone(AMS)
        p = {"id": ruuid(), "metric": metric,
             "profile": {"email": email, "external_id": str(klant_id) if klant_id else None},
             "campaign": campagne, "flow": flow,
             "timestamp": lokaal.isoformat(timespec="seconds")}
        if extra:
            p["properties"] = extra
        return p

    def _verstuur(self, email, ts, campagne, flow, utm_campaign):
        ab = self.abonnees.get(email)
        kid = ab["klant_id"] if ab else None
        evts = self.email_events
        evts[lokale_datum(ts)].append(self._email_event("Received Email", ts, email, kid, campagne, flow))
        kans_open = 0.42 if flow else 0.31
        if R.random() < kans_open:
            t_open = ts + timedelta(minutes=R.expovariate(1 / 240))
            evts[lokale_datum(t_open)].append(self._email_event("Opened Email", t_open, email, kid, campagne, flow))
            if R.random() < (0.22 if flow else 0.15):
                t_klik = t_open + timedelta(seconds=R.randint(5, 600))
                evts[lokale_datum(t_klik)].append(self._email_event("Clicked Email", t_klik, email, kid, campagne, flow,
                                                                   extra={"url": f"{CONFIG['site']}/?utm_campaign={utm_campaign}"}))
                if R.random() < 0.86:
                    self.email_kliks[lokale_datum(t_klik)].append((t_klik, email, kid, utm_campaign))
            if R.random() < 0.0025:
                t = t_open + timedelta(seconds=R.randint(10, 300))
                evts[lokale_datum(t)].append(self._email_event("Unsubscribed", t, self.vuil_email(email), kid, campagne, flow))
                if ab:
                    ab["actief"] = False   # let op: de webshop hoort dit niet (opt-in blijft daar staan)

    def nieuwsbrief(self, d, nr):
        ts = lokaal_naar_utc(d, 10.0)
        thema = NIEUWSBRIEF_THEMAS[nr % len(NIEUWSBRIEF_THEMAS)]
        if in_bf_periode(d):
            thema = "Black Friday: tot 25% korting"
        week = d.isocalendar()[1]
        naam = f"Nieuwsbrief wk {week} - {thema}"
        camp = {"id": f"cmp_{d.strftime('%Y%m%d')}", "name": naam}
        utm = slug(f"nieuwsbrief wk{week} {thema}")
        for email, ab in list(self.abonnees.items()):
            if ab["actief"]:
                self._verstuur(email, ts + timedelta(seconds=R.randint(0, 900)), camp, None, utm)

    # ------------------------------------------------------------------ simulatie per dag
    def simuleer(self):
        d = CONFIG["start"]
        test = self.nieuwe_klant(lokaal_naar_utc(d - timedelta(days=400), 9.0), gast=False,
                                 identiteit={"voornaam": "Test", "achternaam": "Account", "email": "test@marktvizier.example",
                                             "plaats": PLAATSEN[3]})
        test["nieuwsbrief_opt_in"] = False
        self.test_klant_id = test["klant_id"]
        eind = CONFIG["eind"]
        nieuwsbrief_nr = 0
        t0 = time.time()
        totaal_dagen = (eind - d).days + 1
        dagnr = 0
        while d <= eind:
            dagnr += 1
            self.pas_productwijzigingen_toe(d)
            self.verhuis(d)
            # popup-inschrijvingen
            for _ in range(poisson(26 * self.schaal * (1.6 if in_bf_periode(d) else 1.0))):
                self.schrijf_in(self.maak_identiteit()["email"], lokaal_naar_utc(d, R.choices(range(24), cum_weights=UUR_CUM)[0] + R.random()))
            if d.weekday() == 3:
                nieuwsbrief_nr += 1
                self.nieuwsbrief(d, nieuwsbrief_nr)
            # herhaalintenties van vandaag in de wachtrij; oude intenties vervallen na 30 dagen
            self.wachtrij.extend((d, kid) for kid in self.gepland.pop(d, []))
            self.wachtrij = [(dd, kid) for dd, kid in self.wachtrij if (d - dd).days <= 30]
            R.shuffle(self.wachtrij)
            sessies = self.dag_sessies(d)
            self.schrijf_ga4_dag(d, sessies)
            for oud in [x for x in self.email_events if x < d - timedelta(days=10)]:
                self.schrijf_email_dag(oud)
            if dagnr % 30 == 0 or d == eind:
                print(f"  {d}  dag {dagnr}/{totaal_dagen}  orders tot nu: {len(self.orders):,}  GA4-events: {self.ga4_events:,}  "
                      f"({time.time() - t0:.0f} s)", flush=True)
            d += timedelta(days=1)

    def dag_sessies(self, d):
        jaren = (d - CONFIG["start"]).days / 365.0
        sfac, cfac = bf_factor(d)
        basis = CONFIG["sessies_per_dag"] * self.schaal * MAAND_SEIZOEN[d.month] * WEEKDAG[d.weekday()] * sfac \
            * (1 + CONFIG["groei_per_jaar"]) ** jaren
        sessies = []
        # actieve campagnes vandaag
        g_actief = [c for c in GOOGLE_CAMPAGNES if (not c.get("bf") or in_bf_periode(d)) and (d.month in c.get("maanden", set(range(1, 13))))]
        m_actief = [c for c in META_CAMPAGNES if (not c.get("bf") or in_bf_periode(d))]
        for kanaal, k in KANALEN.items():
            n = poisson(basis * k["aandeel"])
            for _ in range(n):
                camp = None
                if kanaal == "google_ads":
                    camp = gewogen(g_actief, [c["gewicht"] for c in g_actief])
                elif kanaal == "meta_ads":
                    camp = gewogen(m_actief, [c["gewicht"] for c in m_actief])
                conv = (camp["conv"] if camp else k["conversie"]) * cfac
                nieuw_kans = camp["nieuw"] if camp else k["nieuw"]
                ts = lokaal_naar_utc(d, R.choices(range(24), cum_weights=UUR_CUM)[0] + R.random())
                sessies.append(self.maak_sessie(d, ts, kanaal, camp, conv, nieuw_kans))
        # e-mailsessies uit kliks
        for t_klik, email, kid, utm in self.email_kliks.pop(d, []):
            k = self.klanten.get(kid) if kid else None
            sessies.append(self.maak_sessie(d, t_klik, "email", {"utm": utm}, 0.07 * cfac, 0.15 if k else 1.0, klant=k, email=email))
        # telefonische orders (geen sessie)
        for _ in range(poisson(1.1 * self.schaal)):
            ts = lokaal_naar_utc(d, R.uniform(9, 17))
            k = self.kies_klant(d, ts, 0.6)
            self.maak_order(d, ts, k, None, kanaal="telefoon")
        sessies.sort(key=lambda s: s["ts"])
        return sessies

    def kies_klant(self, d, ts, nieuw_kans, voorkeur=None, email=None):
        if voorkeur is not None:
            return voorkeur
        terug = R.random() >= nieuw_kans
        if terug and self.wachtrij:
            _, kid = self.wachtrij.pop()
            k = self.klanten[kid]
            if k["is_gast"]:
                # gast komt terug: nieuwe klantrij met hetzelfde e-mailadres (bekend probleem van de webshop)
                ident = {"voornaam": k["voornaam"], "achternaam": k["achternaam"], "email": k["email_schoon"], "plaats": k["pl"]}
                nk = self.nieuwe_klant(ts, gast=R.random() < 0.6, identiteit=ident)
                nk["loyaliteit"] = k["loyaliteit"]
                nk["pseudo_ids"] = k["pseudo_ids"]
                nk["orders"] = k["orders"]
                return nk
            return k
        if terug and len(self.klanten) > 1:
            # geen geplande herhaling beschikbaar: willekeurige bestaande klant
            return self.klanten[R.randint(self.test_klant_id + 1, self.volgende_klant - 1)] if self.volgende_klant > self.test_klant_id + 1 \
                else self.nieuwe_klant(ts, gast=False)
        ident = None
        if email is None and self.popup_niet_klant and R.random() < 0.22:
            e = self.popup_niet_klant.pop(R.randrange(len(self.popup_niet_klant)))
            ident = self.maak_identiteit()
            ident["email"] = e
        elif email is not None:
            ident = self.maak_identiteit()
            ident["email"] = email.strip().lower()
            try:
                self.popup_niet_klant.remove(ident["email"])
            except ValueError:
                pass
        return self.nieuwe_klant(ts, gast=R.random() < 0.30, identiteit=ident)

    def maak_sessie(self, d, ts, kanaal, camp, conv, nieuw_kans, klant=None, email=None):
        koopt = R.random() < conv
        k = None
        if koopt:
            k = self.kies_klant(d, ts, nieuw_kans, voorkeur=klant, email=email if klant is None else None)
        elif klant is not None:
            k = klant
        pseudo, nieuw_cookie = self.pseudo_id(k)
        s = {"d": d, "ts": ts, "kanaal": kanaal, "camp": camp, "klant": k, "pseudo": pseudo, "nieuw_cookie": nieuw_cookie,
             "koopt": koopt, "ga_session_id": int(ts.timestamp()), "apparaat": gewogen(["mobile", "desktop", "tablet"], [62, 31, 7]),
             "gclid": None, "order": None, "gemeten": R.random() >= 0.07}
        if kanaal == "google_ads":
            s["gclid"] = "Cj0KCQjw" + "".join(R.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-", k=60))
        if koopt:
            s["order"] = self.maak_order(d, ts + timedelta(seconds=R.randint(180, 1500)), k, s, kanaal)
        return s

    # ------------------------------------------------------------------ orders
    def maak_order(self, d, ts, k, sessie, kanaal):
        oid = self.volgende_order
        self.volgende_order += R.choice([1, 1, 1, 1, 2])   # soms gaten in de nummering (afgebroken checkouts)
        camp = sessie["camp"] if sessie else None
        # producten kiezen
        if camp and camp.get("categorie"):
            pool, cum = self.pool(d, categorie=camp["categorie"])
        elif camp and camp.get("bestsellers"):
            pool, cum = self.pool(d, bestsellers=True)
        else:
            pool, cum = self.pool(d)
        n = gewogen([1, 2, 3, 4], [62, 26, 9, 3])
        gekozen = []
        for _ in range(n):
            p = R.choices(pool, cum_weights=cum)[0]
            if p not in gekozen:
                gekozen.append(p)
        # kortingscode
        code = None
        x = R.random()
        if in_bf_periode(d) and x < 0.62:
            code = R.choice([f"BF{d.year % 100}", f"BF{d.year % 100}", f"bf{d.year % 100}", f"BF{d.year % 100} "])
        elif k and k["orders"] == 0 and x < 0.20:
            code = "WELKOM10"
        elif d.month in (7, 8) and x < 0.15:
            code = "ZOMER15"
        elif x < 0.06:
            code = "NIEUWSBRIEF5"
        pct = {"WELKOM10": 0.10, "ZOMER15": 0.15, "NIEUWSBRIEF5": 0.05}.get(code.strip().upper() if code else "", 0.20 if code else 0.0)
        regels = []
        totaal = 0.0
        for nr, p in enumerate(gekozen, start=1):
            aantal = gewogen([1, 2, 3, 4], [80, 14, 4, 2]) if p["verkoopprijs_incl_btw"] < 60 else 1
            stuk = p["verkoopprijs_incl_btw"]
            korting = euro(aantal * stuk * pct)
            bedrag = euro(aantal * stuk - korting)
            totaal += bedrag
            rij = {"order_id": oid, "regel_nr": nr, "product_id": p["product_id"], "sku": p["sku"], "aantal": aantal,
                   "stukprijs_incl_btw": stuk, "korting_incl_btw": korting if korting else (None if R.random() < 0.5 else 0.0),
                   "regelbedrag_incl_btw": bedrag, "btw_tarief": p["btw_tarief"]}
            # vervuiling in orderregels
            y = R.random()
            if y < 0.002:
                rij["stukprijs_incl_btw"] = -stuk           # tekenfout
            elif y < 0.005:
                rij["regelbedrag_incl_btw"] = 0.0           # bedrag niet opgeslagen
            elif y < 0.007:
                rij["regelbedrag_incl_btw"] = euro(bedrag * 1.21)   # dubbele btw
            regels.append((rij, p))
        verzend = 0.0 if totaal >= 75 else 4.95
        test = R.random() < 0.004
        if test:
            k = self.klanten[self.test_klant_id]
        betaal = "bancontact" if (k and k["land_echt"] == "BE" and R.random() < 0.6) else \
            gewogen(["ideal", "iDEAL", "creditcard", "paypal", "klarna"], [52, 8, 14, 14, 12])
        o = {"order_id": oid, "klant_id": k["klant_id"] if k else None, "besteld_op": ts, "status": "pending",
             "betaalmethode": betaal, "kortingscode": code if code else R.choice([None, ""]),
             "verzendkosten_incl_btw": verzend, "verzonden_op": None, "is_testorder": test, "valuta": "EUR",
             "land_levering": k["land_echt"] if k else "NL", "kanaal_echt": kanaal, "totaal_incl_btw": euro(totaal),
             "regels": regels, "sessie": sessie}
        self.orders.append(o)
        self._order_versie(o, ts)
        for rij, _ in regels:
            r = dict(rij)
            r.pop("sku")
            r["datastream_metadata"] = {"uuid": ruuid(), "source_timestamp": ms(ts)}
            self.regels.append((ts, r))
        # statusverloop
        t = ts
        if R.random() < 0.97:
            t = t + timedelta(minutes=R.randint(1, 20))
            o["status"] = "Paid" if R.random() < 0.01 else "paid"
            self._order_versie(o, t)
            if R.random() < 0.04:
                t = t + timedelta(hours=R.randint(1, 40))
                o["status"] = "canceled" if t < datetime(2025, 9, 1, tzinfo=UTC) else "cancelled"
                self._order_versie(o, t)
            else:
                if d >= date(2026, 9, 15) and R.random() < 0.012:
                    t = t + timedelta(hours=R.randint(2, 30))
                    o["status"] = "on_hold"           # nieuwe status sinds een webshopupdate
                    self._order_versie(o, t)
                    t = t + timedelta(hours=R.randint(2, 400))
                t = t + timedelta(hours=R.randint(14, 70))
                o["status"] = "shipped"
                o["verzonden_op"] = t if R.random() > 0.005 else o["besteld_op"] - timedelta(days=1)   # invoerfout
                self._order_versie(o, t)
                retour = 0.10 if any(p["categorie"] in ("Textiel", "Slapen") for _, p in regels) else 0.05
                if R.random() < retour:
                    t = t + timedelta(days=R.randint(3, 28))
                    o["status"] = "returned"
                    self._order_versie(o, t)
        else:
            t = t + timedelta(hours=R.randint(1, 30))
            o["status"] = "cancelled" if t >= datetime(2025, 9, 1, tzinfo=UTC) else "canceled"
            self._order_versie(o, t)
        # herhaalintentie
        if k and not test and o["status"] not in ("cancelled", "canceled"):
            k["orders"] += 1
            kans = (0.20 if k["is_gast"] else 0.30) + 0.35 * k["loyaliteit"] + (0.12 if k["orders"] > 1 else 0)
            if R.random() < min(kans, 0.85):
                dagen = int(R.lognormvariate(math.log(70), 0.75)) + 7
                self.gepland[d + timedelta(days=dagen)].append(k["klant_id"])
        return o

    def _order_versie(self, o, ts):
        rij = {"order_id": o["order_id"], "klant_id": o["klant_id"], "besteld_op": iso(o["besteld_op"]), "status": o["status"],
               "betaalmethode": o["betaalmethode"], "kortingscode": o["kortingscode"], "verzendkosten_incl_btw": o["verzendkosten_incl_btw"],
               "verzonden_op": iso(o["verzonden_op"]) if o["verzonden_op"] else None, "is_testorder": o["is_testorder"],
               "valuta": o["valuta"], "land_levering": o["land_levering"], "gewijzigd_op": iso(ts),
               "datastream_metadata": {"uuid": ruuid(), "source_timestamp": ms(ts)}}
        self.order_versies.append((ts, rij))

    # ------------------------------------------------------------------ GA4
    def herkomst(self, s):
        """Geeft (collected_traffic_source, event_params bron/medium, landings-URL-query) voor de eerste events."""
        k, camp = s["kanaal"], s["camp"]
        cts, bronparams, query = None, {}, ""
        if k == "google_ads":
            cts = {"manual_campaign_id": None, "manual_campaign_name": None, "manual_source": None, "manual_medium": None,
                   "manual_term": None, "manual_content": None, "gclid": s["gclid"], "dclid": None, "srsltid": None}
            query = f"?gclid={s['gclid']}"
            if R.random() < 0.3:   # een deel van de campagnes heeft ook UTM's in de tracking-template
                cts.update({"manual_source": "google", "manual_medium": "cpc", "manual_campaign_name": slug(camp["naam"]),
                            "manual_campaign_id": str(camp["id"])})
                query += f"&utm_source=google&utm_medium=cpc&utm_campaign={slug(camp['naam'])}"
        elif k == "meta_ads":
            bron = gewogen(["facebook", "Facebook", "fb", "instagram", "ig"], [50, 10, 10, 25, 5])
            medium = gewogen(["paid_social", "cpc", "Paid Social"], [70, 20, 10])
            naam = slug(camp["naam"]) if R.random() < 0.8 else camp["naam"]
            cts = {"manual_campaign_id": camp["id"] if R.random() < 0.5 else None, "manual_campaign_name": naam,
                   "manual_source": bron, "manual_medium": medium, "manual_term": None, "manual_content": None,
                   "gclid": None, "dclid": None, "srsltid": None}
            query = f"?utm_source={bron}&utm_medium={medium.replace(' ', '+')}&utm_campaign={naam.replace(' ', '+')}&fbclid=IwAR{R.randint(10**9, 10**10)}"
        elif k == "email":
            bron = gewogen(["nieuwsbrief", "klaviyo", "Nieuwsbrief"], [60, 30, 10])
            medium = gewogen(["email", "e-mail", "Email"], [70, 20, 10])
            cts = {"manual_campaign_id": None, "manual_campaign_name": camp["utm"], "manual_source": bron, "manual_medium": medium,
                   "manual_term": None, "manual_content": None, "gclid": None, "dclid": None, "srsltid": None}
            query = f"?utm_source={bron}&utm_medium={medium}&utm_campaign={camp['utm']}"
        elif k == "organisch":
            bronparams = {"source": gewogen(["google", "bing", "duckduckgo", "ecosia"], [80, 10, 5, 5]), "medium": "organic"}
        elif k == "social":
            bronparams = {"source": gewogen(["instagram.com", "pinterest.com", "l.facebook.com", "linkedin.com"], [45, 30, 20, 5]),
                          "medium": "referral"}
        elif k == "verwijzing":
            bronparams = {"source": gewogen(["wonenmetaandacht.example", "duurzaamthuis.example", "vergelijk.example"], [40, 35, 25]),
                          "medium": "referral"}
        return cts, bronparams, query

    def schrijf_ga4_dag(self, d, sessies):
        regels, laat = [], []
        sessie_nr = defaultdict(int)
        for s in sessies:
            if not s["gemeten"]:
                continue
            evs = self.ga4_events_sessie(s, sessie_nr)
            for e, is_laat in evs:
                regels.append(json.dumps(e, ensure_ascii=False, separators=(",", ":")))
                laat.append(is_laat)
        self.ga4_events += len(regels)
        naam = f"events_{d.strftime('%Y%m%d')}.ndjson.gz"
        if d <= CONFIG["backfill_tot"]:
            self.uit.ndjson_regels(regels, "backfill", "ga4", naam)
        else:
            volledig = d + timedelta(days=2)
            eerst = d + timedelta(days=1)
            if volledig <= CONFIG["eind"]:
                self.uit.ndjson_regels(regels, "dagelijks", volledig.isoformat(), "ga4", naam)
            if eerst <= CONFIG["eind"]:
                self.uit.ndjson_regels([r for r, l in zip(regels, laat) if not l], "dagelijks", eerst.isoformat(), "ga4", naam)
        # Google Ads- en Meta-statistieken uit dezelfde sessies (ook ongemeten sessies hebben een klik)
        for s in sessies:
            if s["kanaal"] == "google_ads":
                key = (d, s["camp"]["id"], s["apparaat"])
                st = self.google_stats[key]
                st["sessies"] += 1
                st["conversies"] += 1 if s["koopt"] else 0
                st["waarde"] += s["order"]["totaal_incl_btw"] if s["koopt"] else 0
                self.google_clicks[d].append((s["gclid"], s["camp"]["id"], s["apparaat"].upper()))
            elif s["kanaal"] == "meta_ads":
                st = self.meta_stats[(d, s["camp"]["id"])]
                st["sessies"] += 1
                st["conversies"] += 1 if s["koopt"] else 0
                st["waarde"] += s["order"]["totaal_incl_btw"] if s["koopt"] else 0

    def ga4_events_sessie(self, s, sessie_nr):
        k = s["klant"]
        pseudo = s["pseudo"]
        sessie_nr[pseudo] += 1
        ts = s["ts"]
        cts, bronparams, query = self.herkomst(s)
        apparaat = s["apparaat"]
        os_ = {"mobile": gewogen(["iOS", "Android"], [55, 45]), "desktop": gewogen(["Windows", "Macintosh", "Linux"], [62, 34, 4]),
               "tablet": gewogen(["iOS", "Android"], [70, 30])}[apparaat]
        browser = {"iOS": "Safari", "Macintosh": "Safari"}.get(os_, gewogen(["Chrome", "Edge", "Firefox"], [75, 15, 10]))
        pl = k["pl"] if k else R.choices(PLAATSEN, cum_weights=PLAATS_CUM)[0]
        geo = {"city": pl[0], "country": "Netherlands" if pl[4] == "NL" else "Belgium", "continent": "Europe",
               "region": pl[1], "sub_continent": "Western Europe", "metro": "(not set)"}
        eerste_aanraking = us(ts) if s["nieuw_cookie"] else us(ts) - R.randint(1, 400) * 86400 * 1_000_000
        if s["kanaal"] in ("google_ads", "meta_ads", "email"):
            ts_bron = {"name": (cts or {}).get("manual_campaign_name") or "(cpc)", "medium": (cts or {}).get("manual_medium") or "cpc",
                       "source": (cts or {}).get("manual_source") or "google"}
        elif bronparams:
            ts_bron = {"name": "(organic)" if bronparams["medium"] == "organic" else "(referral)", "medium": bronparams["medium"],
                       "source": bronparams["source"]}
        else:
            ts_bron = {"name": "(direct)", "medium": "(none)", "source": "(direct)"}
        if not s["nieuw_cookie"] and R.random() < 0.6:
            ts_bron = {"name": "(direct)", "medium": "(none)", "source": "(direct)"}   # first-touch van eerder bezoek
        o = s["order"]
        # paginaverloop
        if o:
            items = [p for _, p in o["regels"]]
            paginas = ["/"] + [f"/p/{p['sku'].lower()}" for p in items] + ["/winkelwagen", "/afrekenen", "/bedankt"]
        else:
            n = 1 if R.random() < 0.42 else min(1 + int(R.expovariate(1 / 3)), 15)
            pool = self.actieve_producten(s["d"])
            paginas = []
            for i in range(n):
                if R.random() < 0.55:
                    p = R.choice(pool)
                    paginas.append(f"/p/{p['sku'].lower()}")
                else:
                    paginas.append(R.choice(["/", "/c/textiel", "/c/slapen", "/c/wonen", "/c/keuken", "/c/tuin", "/c/verlichting",
                                             "/c/badkamer", "/over-ons", "/duurzaamheid", "/zoeken"]))
        events = []
        t = ts
        user_id = str(k["klant_id"]) if (k and not k["is_gast"] and o) else None

        def ev(naam, t, params, items=None, ecommerce=None, eerste=False):
            ep = [{"key": "ga_session_id", "value": {"int_value": s["ga_session_id"]}},
                  {"key": "ga_session_number", "value": {"int_value": sessie_nr[pseudo]}},
                  {"key": "engagement_time_msec", "value": {"int_value": R.randint(200, 40000)}}]
            for kk, vv in params.items():
                if isinstance(vv, bool):
                    ep.append({"key": kk, "value": {"string_value": "1" if vv else "0"}})
                elif isinstance(vv, int):
                    ep.append({"key": kk, "value": {"int_value": vv}})
                elif isinstance(vv, float):
                    ep.append({"key": kk, "value": {"double_value": vv}})
                else:
                    ep.append({"key": kk, "value": {"string_value": vv}})
            e = {"event_date": s["d"].strftime("%Y%m%d"),
                 "event_timestamp": us(t), "event_name": naam, "event_params": ep,
                 "event_bundle_sequence_id": R.randint(1, 10**9), "user_id": user_id if naam in ("purchase", "begin_checkout") else None,
                 "user_pseudo_id": pseudo, "user_first_touch_timestamp": eerste_aanraking,
                 "device": {"category": apparaat, "operating_system": os_, "language": "nl-nl" if geo["country"] == "Netherlands" else "nl-be",
                            "web_info": {"browser": browser, "hostname": "www.marktvizier.example"}},
                 "geo": geo, "traffic_source": ts_bron, "stream_id": CONFIG["ga4_stream_id"], "platform": "WEB",
                 "collected_traffic_source": cts if eerste else None,
                 "ecommerce": ecommerce, "items": items or []}
            return e

        loc = lambda pad, q="": f"{CONFIG['site']}{pad}{q}"
        eerste_params = dict(bronparams)
        eerste_params.update({"page_location": loc(paginas[0], query), "page_title": "MarktVizier | Duurzaam wonen"})
        if s["nieuw_cookie"]:
            events.append((ev("first_visit", t, {"page_location": loc(paginas[0], query)}, eerste=True), False))
        events.append((ev("session_start", t, eerste_params, eerste=True), False))
        events.append((ev("page_view", t, eerste_params, eerste=True), False))
        for pad in paginas[1:]:
            t = t + timedelta(seconds=R.randint(8, 140))
            events.append((ev("page_view", t, {"page_location": loc(pad), "page_title": "MarktVizier"}), False))
            if pad.startswith("/p/"):
                sku = pad[3:].upper()
                p = self.sku_index.get(sku)
                if p:
                    it = [{"item_id": p["sku"], "item_name": p["productnaam"], "item_brand": p["merk"], "item_category": p["categorie"],
                           "price": p["verkoopprijs_incl_btw"], "quantity": 1, "item_revenue": None}]
                    events.append((ev("view_item", t + timedelta(seconds=1), {"currency": "EUR", "value": float(p["verkoopprijs_incl_btw"])}, it), False))
                    if o is None and R.random() < 0.08:
                        events.append((ev("add_to_cart", t + timedelta(seconds=R.randint(5, 60)),
                                          {"currency": "EUR", "value": float(p["verkoopprijs_incl_btw"])}, it), False))
        if o:
            items = [{"item_id": r["sku"], "item_name": p["productnaam"], "item_brand": p["merk"], "item_category": p["categorie"],
                      "price": r["stukprijs_incl_btw"], "quantity": r["aantal"], "item_revenue": r["regelbedrag_incl_btw"]}
                     for r, p in o["regels"]]
            waarde = euro(sum(r["regelbedrag_incl_btw"] for r, _ in o["regels"]))
            t_koop = o["besteld_op"]
            events.append((ev("add_to_cart", t_koop - timedelta(seconds=120), {"currency": "EUR", "value": float(waarde)}, items), False))
            events.append((ev("begin_checkout", t_koop - timedelta(seconds=60), {"currency": "EUR", "value": float(waarde)}, items), False))
            tid = str(o["order_id"])
            if o["besteld_op"] >= datetime(2026, 3, 1, tzinfo=UTC):
                tid = "MV-" + tid                       # tagwijziging na een nieuwe thema-release
            ecom = {"transaction_id": tid, "purchase_revenue": float(waarde), "purchase_revenue_in_usd": None,
                    "shipping_value": float(o["verzendkosten_incl_btw"]), "tax_value": float(euro(waarde - waarde / 1.21)),
                    "total_item_quantity": sum(r["aantal"] for r, _ in o["regels"]), "unique_items": len(o["regels"]),
                    "refund_value": None}
            params = {"transaction_id": tid, "currency": "EUR", "value": float(waarde), "shipping": float(o["verzendkosten_incl_btw"]),
                      "page_location": loc("/bedankt")}
            if o["kortingscode"]:
                params["coupon"] = o["kortingscode"].strip()
            events.append((ev("purchase", t_koop + timedelta(seconds=3), params, items, ecom), R.random() < 0.04))
            if R.random() < 0.015:   # bedankpagina opnieuw geladen: dubbele purchase
                events.append((ev("purchase", t_koop + timedelta(seconds=R.randint(20, 400)), params, items, ecom), False))
        # 3% van alle events komt laat binnen (alleen relevant voor de dagelijkse leveringen)
        return [(e, l or R.random() < 0.03) for e, l in events]

    # ------------------------------------------------------------------ advertentieplatformen
    def ads_rijen(self):
        """Bouwt de Google Ads- en Meta-tabellen uit de sessiestatistieken."""
        g_stats, g_camp, g_click = [], [], []
        for (d, cid, dev), st in sorted(self.google_stats.items()):
            c = next(x for x in GOOGLE_CAMPAGNES if x["id"] == cid)
            kliks = max(1, int(round(st["sessies"] / R.uniform(0.86, 0.94))))
            cpc = c["cpc"] * R.uniform(0.85, 1.15) * (1.25 if in_bf_periode(d) else 1.0)
            kosten = kliks * cpc
            vert = int(kliks / (c["ctr"] * R.uniform(0.8, 1.2)))
            conv = st["conversies"] * R.uniform(1.05, 1.35)          # Ads telt ook view-through en cross-device
            g_stats.append({"campaign_id": cid, "segments_date": d.isoformat(), "segments_device": dev.upper(),
                            "segments_ad_network_type": "SEARCH" if c["type"] == "SEARCH" else ("SHOPPING" if c["type"] == "SHOPPING" else "MIXED"),
                            "metrics_impressions": vert, "metrics_clicks": kliks, "metrics_cost_micros": int(kosten * 1_000_000),
                            "metrics_conversions": round(conv, 2), "metrics_conversions_value": round(st["waarde"] * R.uniform(1.0, 1.25), 2),
                            "_DATA_DATE": d.isoformat(), "_LATEST_DATE": CONFIG["eind"].isoformat()})
            st["kliks"] = kliks
        for d, kliks in sorted(self.google_clicks.items()):
            for gclid, cid, dev in kliks:
                g_click.append({"click_view_gclid": gclid, "segments_date": d.isoformat(), "campaign_id": cid,
                                "segments_device": dev, "click_view_ad_group_ad": None, "_DATA_DATE": d.isoformat(),
                                "_LATEST_DATE": CONFIG["eind"].isoformat()})
            # kliks zonder sessie (pagina niet geladen, consent geweigerd vóór laden)
            for _ in range(int(len(kliks) * 0.1)):
                gclid, cid, dev = R.choice(kliks)
                g_click.append({"click_view_gclid": "Cj0KCQjw" + "".join(R.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-", k=60)),
                                "segments_date": d.isoformat(), "campaign_id": cid, "segments_device": dev, "click_view_ad_group_ad": None,
                                "_DATA_DATE": d.isoformat(), "_LATEST_DATE": CONFIG["eind"].isoformat()})
        d = CONFIG["start"]
        while d <= CONFIG["eind"]:
            for c in GOOGLE_CAMPAGNES:
                naam = c["naam"]
                if c.get("hernoemd") and d >= c["hernoemd"][0]:
                    naam = c["hernoemd"][1]
                actief = (not c.get("bf") or in_bf_periode(d)) and d.month in c.get("maanden", set(range(1, 13)))
                g_camp.append({"campaign_id": c["id"], "campaign_name": naam, "campaign_status": "ENABLED" if actief else "PAUSED",
                               "campaign_advertising_channel_type": c["type"], "customer_id": int(CONFIG["google_ads_klant_id"]),
                               "_DATA_DATE": d.isoformat(), "_LATEST_DATE": CONFIG["eind"].isoformat()})
            d += timedelta(days=1)
        meta = []
        for (d, cid), st in sorted(self.meta_stats.items()):
            c = next(x for x in META_CAMPAGNES if x["id"] == cid)
            kliks = max(1, int(round(st["sessies"] / R.uniform(0.74, 0.84))))
            spend = kliks * c["cpc"] * R.uniform(0.85, 1.15) * (1.2 if in_bf_periode(d) else 1.0)
            vert = int(kliks / (c["ctr"] * R.uniform(0.8, 1.2)))
            meta.append({"date_start": d.isoformat(), "date_stop": d.isoformat(), "account_id": CONFIG["meta_account_id"],
                         "campaign_id": cid, "campaign_name": c["naam"], "impressions": vert, "clicks": kliks,
                         "spend": f"{spend:.2f}", "actions_purchase": int(round(st["conversies"] * R.uniform(1.1, 1.6))),
                         "action_values_purchase": f"{st['waarde'] * R.uniform(1.1, 1.5):.2f}"})
        return g_stats, g_camp, g_click, meta

    # ------------------------------------------------------------------ leveranciers
    def leveranciersbestanden(self):
        """Noorderlicht: elke maandag volledige prijslijst (UTF-8, puntkomma, punt-decimaal, JJJJ-MM-DD).
        Hout & Heem: elke 1e van de maand (Windows-1252, puntkomma, decimale komma, DD-MM-JJJJ, Ja/Nee,
        artikelcode in kleine letters, sinds juni 2026 een extra kolom achteraan)."""
        bestanden = []   # (datum, map, bestandsnaam, kop, rijen, codering)
        d = CONFIG["start"]
        while d <= CONFIG["eind"]:
            if d.weekday() == 0:
                rijen = []
                for p in self.producten:
                    if p["lev"] != "noorderlicht" or p["lancering"] > d + timedelta(days=30):
                        continue
                    vanaf = max([v for v, _ in self.inkoop[p["sku"]] if v <= d] or [d])
                    prijs = self.inkoopprijs(p["sku"], d)
                    rijen.append([p["sku"], p["productnaam"], f"{prijs:.2f}", vanaf.isoformat(), "stuk"])
                bestanden.append((d, "noorderlicht", f"prijzen_{d.strftime('%Y%m%d')}.csv",
                                  ["artikelnummer", "omschrijving", "inkoopprijs", "geldig_vanaf", "eenheid"], rijen, "utf-8"))
            if d.day == 1:
                nieuw_formaat = d >= date(2026, 6, 1)
                kop = ["Artikelcode", "Omschrijving", "Inkoopprijs (EUR)", "Geldig vanaf", "Op voorraad"] + (["Levertijd (dagen)"] if nieuw_formaat else [])
                rijen = []
                for p in self.producten:
                    if p["lev"] != "houtheem" or p["lancering"] > d + timedelta(days=30):
                        continue
                    vanaf = max([v for v, _ in self.inkoop[p["sku"]] if v <= d] or [d])
                    prijs = self.inkoopprijs(p["sku"], d)
                    prijs_txt = f"{prijs:.2f}".replace(".", ",")
                    y = R.random()
                    if y < 0.01:
                        prijs_txt = ""
                    elif y < 0.015:
                        prijs_txt = "0,00"
                    rij = [p["sku"].lower(), p["productnaam"], prijs_txt, vanaf.strftime("%d-%m-%Y"),
                           "Ja" if R.random() < 0.9 else "Nee"]
                    if nieuw_formaat:
                        rij.append(str(R.choice([3, 5, 5, 7, 10, 14])))
                    rijen.append(rij)
                bestanden.append((d, "houtheem", f"prijslijst_{d.strftime('%Y-%m')}.csv", kop, rijen, "cp1252"))
            d += timedelta(days=1)
        return bestanden

    # ------------------------------------------------------------------ wegschrijven
    def schrijf_email_dag(self, dag):
        evts = self.email_events.pop(dag, [])
        bt = CONFIG["backfill_tot"]
        if dag > CONFIG["eind"] or not evts:
            return
        evts.sort(key=lambda e: e["timestamp"])
        geladen = datetime.combine(dag + timedelta(days=1), datetime.min.time(), tzinfo=AMS).astimezone(UTC) \
            + timedelta(hours=2, minutes=R.randint(0, 20))
        rijen = [{"payload": e, "geladen_voor_datum": dag.isoformat(), "dwh_geladen_op": iso(geladen)} for e in evts]
        if dag <= bt:
            self.uit.ndjson(rijen, "backfill", "email", f"events_{dag.strftime('%Y%m%d')}.ndjson.gz")
        elif dag + timedelta(days=1) <= CONFIG["eind"]:
            self.uit.ndjson(rijen, "dagelijks", (dag + timedelta(days=1)).isoformat(), "email", f"events_{dag.strftime('%Y%m%d')}.ndjson.gz")
        self.email_bestanden += 1

    def schrijf_alles(self):
        uit = self.uit
        bt = CONFIG["backfill_tot"]
        grens = datetime(bt.year, bt.month, bt.day, tzinfo=AMS).astimezone(UTC) + timedelta(days=1)

        def laatste_stand(versies, sleutel):
            stand = {}
            for ts, rij in versies:
                if ts < grens:
                    k = sleutel(rij)
                    if k not in stand or stand[k][0] <= ts:
                        stand[k] = (ts, rij)
            return [r for _, r in sorted(stand.values(), key=lambda x: x[0])]

        # --- webshop: backfill
        print("  webshop wegschrijven ...", flush=True)
        uit.ndjson(laatste_stand(self.klant_versies, lambda r: r["klant_id"]), "backfill", "webshop", "klanten.ndjson.gz")
        uit.ndjson(laatste_stand(self.order_versies, lambda r: r["order_id"]), "backfill", "webshop", "orders.ndjson.gz")
        uit.ndjson([r for ts, r in self.regels if ts < grens], "backfill", "webshop", "orderregels.ndjson.gz")
        uit.ndjson([r for ts, r in sorted(self.product_versies, key=lambda x: x[0]) if ts < grens], "backfill", "webshop", "producten.ndjson.gz")
        # --- webshop: dagelijkse wijzigingen (alle versies van die dag; klanten soms dubbel)
        per_dag = defaultdict(lambda: defaultdict(list))
        for naam, versies in (("klanten", self.klant_versies), ("orders", self.order_versies), ("orderregels", self.regels),
                              ("producten", self.product_versies)):
            for ts, rij in versies:
                if ts >= grens:
                    dag = lokale_datum(ts)
                    if dag <= CONFIG["eind"]:
                        per_dag[dag][naam].append(rij)
                        if naam == "klanten" and R.random() < 0.05:
                            per_dag[dag][naam].append(dict(rij))   # exact dubbele CDC-levering
        for dag, tabellen in per_dag.items():
            for naam in ("klanten", "orders", "orderregels", "producten"):
                uit.ndjson(tabellen.get(naam, []), "dagelijks", dag.isoformat(), "webshop", f"{naam}.ndjson.gz")

        # --- e-mail (rest van de dagen)
        print("  e-mailplatform wegschrijven ...", flush=True)
        for dag in sorted(self.email_events):
            self.schrijf_email_dag(dag)

        # --- advertenties
        print("  Google Ads en Meta wegschrijven ...", flush=True)
        g_stats, g_camp, g_click, meta = self.ads_rijen()
        cid = CONFIG["google_ads_klant_id"]
        uit.ndjson([r for r in g_stats if r["segments_date"] <= bt.isoformat()], "backfill", "google_ads", f"ads_CampaignBasicStats_{cid}.ndjson.gz")
        uit.ndjson([r for r in g_camp if r["_DATA_DATE"] <= bt.isoformat()], "backfill", "google_ads", f"ads_Campaign_{cid}.ndjson.gz")
        uit.ndjson([r for r in g_click if r["segments_date"] <= bt.isoformat()], "backfill", "google_ads", f"ads_ClickStats_{cid}.ndjson.gz")
        meta_kop = list(meta[0].keys())
        uit.csvbestand(meta_kop, [[r[k] for k in meta_kop] for r in meta if r["date_start"] <= bt.isoformat()],
                       "backfill", "meta", "meta_ad_insights.csv")
        dag = bt + timedelta(days=1)
        while dag <= CONFIG["eind"]:
            venster = [(dag - timedelta(days=i)).isoformat() for i in range(1, 8)]
            gisteren = venster[0]

            def eerste_versie(r, kliksveld, kostveld, micros):
                r = dict(r)
                if r.get("segments_date", r.get("date_start")) == gisteren:   # eerste levering: nog niet gecorrigeerd
                    r[kliksveld] = int(round(r[kliksveld] * 1.012)) + 1
                    if micros:
                        r[kostveld] = int(r[kostveld] * 1.011)
                    else:
                        r[kostveld] = f"{float(r[kostveld]) * 1.011:.2f}"
                r["_DATA_DATE"] = r.get("segments_date") or r.get("_DATA_DATE")
                return r
            d_str = dag.isoformat()
            uit.ndjson([eerste_versie(r, "metrics_clicks", "metrics_cost_micros", True) for r in g_stats if r["segments_date"] in venster],
                       "dagelijks", d_str, "google_ads", f"ads_CampaignBasicStats_{cid}.ndjson.gz")
            uit.ndjson([r for r in g_camp if r["_DATA_DATE"] == gisteren], "dagelijks", d_str, "google_ads", f"ads_Campaign_{cid}.ndjson.gz")
            uit.ndjson([r for r in g_click if r["segments_date"] == gisteren], "dagelijks", d_str, "google_ads", f"ads_ClickStats_{cid}.ndjson.gz")
            mrij = []
            for r in meta:
                if r["date_start"] in venster:
                    x = dict(r)
                    if x["date_start"] == gisteren:
                        x["clicks"] = int(round(x["clicks"] * 1.015)) + 1
                        x["spend"] = f"{float(x['spend']) * 1.01:.2f}"
                    mrij.append([x[k] for k in meta_kop])
            uit.csvbestand(meta_kop, mrij, "dagelijks", d_str, "meta", f"meta_ad_insights_{dag.strftime('%Y%m%d')}.csv")
            dag += timedelta(days=1)

        # --- leveranciers
        print("  leveranciersbestanden wegschrijven ...", flush=True)
        for d, lev, naam, kop, rijen, codering in self.leveranciersbestanden():
            sch = ";"
            if d <= bt:
                uit.csvbestand(kop, rijen, "backfill", "leveranciers", lev, naam, scheiding=sch, codering=codering)
            else:
                uit.csvbestand(kop, rijen, "dagelijks", d.isoformat(), "leveranciers", lev, naam, scheiding=sch, codering=codering)

        # --- antwoordsleutel voor controles (niet laden in het warehouse!)
        sleutel = []
        for o in self.orders:
            s = o["sessie"]
            sleutel.append({"order_id": o["order_id"], "echt_kanaal": o["kanaal_echt"],
                            "campagne": (s["camp"].get("naam") or s["camp"].get("utm")) if s and s["camp"] else None,
                            "gemeten_in_ga4": bool(s and s["gemeten"]), "besteld_op": iso(o["besteld_op"]),
                            "status_eind": o["status"], "is_testorder": o["is_testorder"],
                            "inkoopwaarde": euro(sum(r["aantal"] * self.inkoopprijs(p["sku"], lokale_datum(o["besteld_op"])) for r, p in o["regels"])),
                            "omzet_excl_btw": euro(sum((r["regelbedrag_incl_btw"] if r["regelbedrag_incl_btw"] > 0 and r["stukprijs_incl_btw"] > 0
                                                        else r["aantal"] * abs(r["stukprijs_incl_btw"]) - (r["korting_incl_btw"] or 0))
                                                       / (1 + r["btw_tarief"]) for r, p in o["regels"]))})
        uit.ndjson(sleutel, "_antwoordsleutel", "orders_waarheid.ndjson.gz")


def main():
    ap = argparse.ArgumentParser(description="MarktVizier-datagenerator")
    ap.add_argument("--uitvoer", default="data", help="uitvoermap (standaard ./data)")
    ap.add_argument("--schaal", type=float, default=1.0, help="volume ten opzichte van MarktVizier (1.0 = ± 1.800 orders/maand)")
    ap.add_argument("--seed", type=int, default=42, help="zelfde seed = zelfde data")
    args = ap.parse_args()
    R.seed(args.seed)
    uitmap = os.path.expanduser(args.uitvoer)
    if os.path.exists(os.path.join(uitmap, "backfill")):
        print(f"Let op: {uitmap}/backfill bestaat al. Verwijder de map eerst (rm -rf {uitmap}) of kies --uitvoer.")
        sys.exit(1)
    t0 = time.time()
    print(f"MarktVizier-datagenerator  |  schaal {args.schaal}  |  seed {args.seed}  |  uitvoer {uitmap}")
    w = Wereld(args.schaal, Uitvoer(uitmap))
    print("1/3  catalogus opbouwen ...", flush=True)
    w.bouw_catalogus()
    print("2/3  dagen simuleren (webshop, GA4, e-mail, advertenties) ...", flush=True)
    w.simuleer()
    print("3/3  bestanden wegschrijven ...", flush=True)
    w.schrijf_alles()
    print(f"\nKlaar in {time.time() - t0:.0f} s:  {len(w.producten)} producten, {len(w.klanten):,} klantrijen, "
          f"{len(w.orders):,} orders, {w.ga4_events:,} GA4-events.")
    print(f"Volgende stap: python3 controleer.py --uitvoer {args.uitvoer}")


if __name__ == "__main__":
    main()
