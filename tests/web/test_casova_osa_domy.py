"""Test časové osy, domů a převodu do S-JTSK v export_web.py (bez sítě, bez Node).

Z kořene repozitáře:
  python3 -I tests/web/test_casova_osa_domy.py skills/rodokmen
"""
import os, sys

SKILL = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "skills/rodokmen")
sys.path.insert(0, os.path.join(SKILL, "tools"))
import export_web as ew  # noqa: E402

vysledky = []


def check(nazev, ok, detail=""):
    vysledky.append(bool(ok))
    print(f"[{'OK ' if ok else 'CHYBA'}] {nazev}{'' if ok else '  ' + str(detail)[:800]}", flush=True)


# S-JTSK proti GeometryServeru ČÚZK (EPSG:4326 → 5514, transformace 1623), tolerance 2 m
for (lat, lon), (x, y) in {(50.0875, 14.4214): (-742798.8, -1043010.5), (49.1951, 16.6068): (-598248.8, -1160744.7),
                           (49.8347, 18.2820): (-470652.6, -1101653.7)}.items():
    gx, gy = ew.wgs84_to_sjtsk(lat, lon)
    check(f"S-JTSK {lat},{lon}", abs(gx - x) < 2 and abs(gy - y) < 2, (gx, gy))

people = {
    "jan": dict(slug="jan", spouse="josefa", line=8, facts=["* 14. 2. 1890 Holice čp. 112", "kovář", "× 20. 6. 1919 Holice Josefa Pokorná", "† 1944 Holice"]),
    "josefa": dict(slug="josefa", spouse="jan", line=8, facts=["* 1895 Dolní Roveň čp. 7", "× 20. 6. 1919 Holice Jan Novák"]),
    "josef": dict(slug="josef", spouse=None, line=9, facts=["sedlák v Dolní Rovni č. p. 7", "* asi 1865 Dolní Roveň"]),
}
ev = ew.timeline(people)
check("osa: 5 událostí (sňatek jednou)", len(ev) == 5, ev)
s = [e for e in ev if e["kind"] == "×"]
check("osa: sňatek má oba manžele", len(s) == 1 and sorted(s[0]["people"]) == ["jan", "josefa"], s)
check("osa: datum s dnem", any(e["date"] == "14. 2. 1890" for e in ev), ev)
check("osa: seřazeno podle roku", [e["year"] for e in ev] == sorted(e["year"] for e in ev), ev)

mista = {"Holice": {"re": "Holic", "lat": 50.0663, "lon": 15.9859, "domy": {"112": [50.067, 15.987]}},
         "Dolní Roveň": {"re": "Dolní Rov", "lat": 50.0293, "lon": 15.9677}}
hs = {f"{h['place']} {h['cp']}": h for h in ew.houses(people, mista)}
check("domy: Holice 112 a Dolní Roveň 7", sorted(hs) == ["Dolní Roveň 7", "Holice 112"], list(hs))
check("domy: zaměřená poloha", hs["Holice 112"]["exact"] and hs["Holice 112"]["lat"] == 50.067, hs["Holice 112"])
check("domy: skloňovaná obec a „č. p.“", {r["slug"] for r in hs["Dolní Roveň 7"]["people"]} == {"josefa", "josef"}, hs["Dolní Roveň 7"])
check("domy: odkaz ČÚZK Archiv", hs["Holice 112"]["cuzk"].startswith("https://ags.cuzk.gov.cz/archiv/?extentstring=-63"), hs["Holice 112"]["cuzk"])

check("země: Pardubický kraj = Čechy", ew.zeme({"osm": "Holice, okres Pardubice, Pardubický kraj, Česko"}) == "Čechy")
check("země: Zlínský kraj = Morava", ew.zeme({"osm": "Vsetín, okres Vsetín, Zlínský kraj, Česko"}) == "Morava")
check("země: okres Opava = Slezsko", ew.zeme({"osm": "Opava, okres Opava, Moravskoslezský kraj, Česko"}) == "Slezsko")
check("země: okres Svitavy = neznámo", ew.zeme({"osm": "Polička, okres Svitavy, Pardubický kraj, Česko"}) is None)
check("země: ruční zápis má přednost", ew.zeme({"zeme": "Čechy", "osm": "Polička, okres Svitavy"}) == "Čechy")

places = [dict(name="Holice", lat=50.0663, lon=15.9859, years=[1700, 1900], hypothesis=False)]
mista2 = {"Holice": {"osm": "Holice, okres Pardubice, Pardubický kraj, Česko"}}
udalosti = [
    {"od": 1866, "do": 1866, "nazev": "Hradec", "text": "", "kruh": [[50.29, 15.74, 50]]},       # ~31 km → ano
    {"od": 1805, "do": 1805, "nazev": "Slavkov", "text": "", "kruh": [[49.153, 16.876, 35]]},     # ~120 km → ne
    {"od": 1656, "do": 1679, "nazev": "Lánové rejstříky", "text": "", "zeme": ["Morava"]},     # jiná země → ne
    {"od": 1770, "do": 1772, "nazev": "Hlad", "text": "", "zeme": ["Čechy", "Morava"]},          # ano
    {"od": 1500, "do": 1520, "nazev": "Dávno", "text": "", "zeme": ["Čechy"]},                   # rod tam ještě nežil → ne
    {"od": 1890, "do": 1890, "nazev": "Požár", "text": "", "mista": ["Holice"]},                 # místní → ano
]
era = {e["nazev"]: e for e in ew.dejiny(places, mista2, udalosti)}
check("dějiny: výběr podle místa a času", sorted(era) == ["Hlad", "Hradec", "Požár"], list(era))
check("dějiny: vzdálenost u okruhu", 25 <= (era.get("Hradec") or {}).get("km", 0) <= 40, era.get("Hradec"))
check("dějiny: data skillu jdou načíst",
      all({"od", "do", "nazev", "text"} <= set(u) and ("zeme" in u or "kruh" in u)
          for u in __import__("json").load(open(os.path.join(SKILL, "tools", "dejiny.json"), encoding="utf-8"))["udalosti"]))

print(f"\n{sum(vysledky)}/{len(vysledky)} v pořádku")
sys.exit(0 if all(vysledky) else 1)
