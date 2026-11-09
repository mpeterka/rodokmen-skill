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

print(f"\n{sum(vysledky)}/{len(vysledky)} v pořádku")
sys.exit(0 if all(vysledky) else 1)
