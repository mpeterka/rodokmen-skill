#!/usr/bin/env python3
"""Export dat rodokmenu (data/*) do webu ve složce web/.

Čte data/osoby.py, data/zaznamy.json, data/svazky.json, data/prepisy.json, data/zvyrazneni.json,
data/mista.json, data/web.json, data/dokumenty.json a markdownové poznámky. Zapisuje
web/src/data/site.json, web/src/generated/*, web/public/{img,zdroje}, web/public/prihlaseni.html,
web/nginx.conf a web/netlify/edge-functions/brana.js.

Spouští se z web/ příkazem `npm run data` (nebo přímo `python3 -I tools/export_web.py`, na Windows `python -I -X utf8 …`).
"""
import hashlib, html, json, os, re, shutil, subprocess, sys, unicodedata
for _s in (sys.stdout, sys.stderr):   # UTF-8 výstup i na Windows bez -X utf8 (cp1250 neumí třeba „→“)
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
DATA = os.path.join(ROOT, "data")
WEB = os.path.join(ROOT, "web")
VYREZY = os.path.join(ROOT, "vyrezy")      # výřezy zápisů a dokumentů (asi 1800 px) – zobrazují se na webu
ZDROJE = os.path.join(ROOT, "zdroje")      # tytéž výřezy v plném rozlišení (proklik)

LINE_COLORS = {8: "#EFB45F", 9: "#F09A78", 10: "#E58AA6", 11: "#B99AE0",
               12: "#86B8E8", 13: "#6FCBB9", 14: "#9CD17A", 15: "#D3D46A"}
STATUS = {"doc": "doloženo matrikou", "prob": "pravděpodobné", "fam": "údaj od rodiny",
          "mh": "jen z cizího rodokmenu", "unk": "neznámé"}
KINDS = {"N": "křest / narození", "O": "sňatek", "Z": "úmrtí", "I": "rejstřík", "S": "sčítání lidu", "J": "jiný pramen"}


def jload(name, default):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_people():
    ns = {}
    exec(open(os.path.join(DATA, "osoby.py"), encoding="utf-8").read(), ns)
    for name, default in (("P", {}), ("SIDE", []), ("LINES", {}), ("ISSUES", []), ("HYPOTEZY", []), ("SAME", {})):
        ns.setdefault(name, default)
    return ns


def record_rows():
    svazky = jload("svazky.json", {})
    rows = []
    for z in jload("zaznamy.json", []):
        sv = svazky.get(z.get("svazek", ""), {})
        key = z["klic"]
        rows.append(dict(
            key=key, kind=z.get("druh", "J"), date=z.get("datum", ""), title=z.get("nazev", key),
            summary=z.get("shrnuti", ""), scan=z.get("snimek", ""),
            archive=sv.get("archiv", ""), volume=sv.get("svazek", ""), vdesc=sv.get("popis", ""),
            portal=sv.get("portal", "archivu"), url=z.get("odkaz") or sv.get("url", ""),
            img=os.path.exists(os.path.join(VYREZY, key + ".jpg")),
            full=os.path.exists(os.path.join(ZDROJE, key + ".jpg")),
        ))
    return rows


def strip_comments(md):
    """Poznámky <!-- … --> v markdownu jsou pro Clauda, ne pro web."""
    return re.sub(r"<!--.*?-->\n?", "", md, flags=re.S)


def slugify(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def norm_answer(text):
    """Stejná normalizace jako v prihlaseni.html: bez diakritiky, malá písmena, jen a-z0-9."""
    t = unicodedata.normalize("NFD", text)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]", "", t)


def years(y):
    y = (y or "").strip()
    ys = re.findall(r"\d{4}", y)
    if not ys:
        return ""
    approx = "≈" if re.match(r"^(asi|≈)", y) else ""
    head, dash, tail = y.partition("–")
    if y.startswith(("?", "†")) or (dash and not re.search(r"\d", head)) or re.match(r"po\b", y):
        # neznámé narození: ukázat jen úmrtí („? – před 1743“ → „† před 1743“, „– po 1921“ → „žil 1921“)
        if re.search(r"\bpo\b", tail or y):
            return "žil " + ys[-1]
        return "† " + ("před " if "před" in y else "") + ys[-1]
    if y.startswith("*"):
        return "* " + ys[0]
    if len(ys) == 1:
        return approx + ys[0]
    second = "?" if "před" in tail else ("po " if re.search(r"\bpo\b", tail) else "") + \
        ("≈" if re.search(r"(asi|≈)", tail) else "") + ys[-1]
    return f"{approx}{ys[0]}–{second}"


def gen(k):
    return k.bit_length() - 1


def relation(k):
    g, male = gen(k), (k % 2 == 0)
    if g == 0:
        return "výchozí osoba rodokmenu"
    if g == 1:
        return "otec" if male else "matka"
    base = "dědeček" if male else "babička"
    if g <= 5:
        return "pra" * (g - 2) + base
    return f"{'předek' if male else 'předkyně'} v {g}. generaci ({'pra' * (g - 2)}{base})"


def placeholder(p):
    return p["n"].startswith(("otec neuveden", "matka neuvedena")) or p["n"] in ("", "?")


def magick_bin():   # ImageMagick 7 (magick), jinak 6 (convert) – ten ale ne na Windows, tam je convert.exe jiný program
    return shutil.which("magick") or (os.name != "nt" and shutil.which("convert")) or None


def size(path):
    w, h = subprocess.run([magick_bin(), path + "[0]", "-format", "%w %h", "info:"],
                          capture_output=True, text=True, check=True).stdout.split()
    return int(w), int(h)


def draw_boxes(src, dst, boxes, small):
    """Kopie výřezu v plném rozlišení s nakreslenými rámečky (pokud má stejný poměr stran jako webový výřez,
    na kterém se rámečky měřily). Vrací False, pak se kopíruje bez rámečků."""
    if not os.path.exists(small) or not magick_bin():
        return False
    (W, H), (w, h) = size(src), size(small)
    if abs(W / H - w / h) > 0.015 * (w / h):
        return False
    sw = max(4, round(W / 450))
    cmd = [magick_bin(), src, "-fill", "none", "-stroke", "#d7302a", "-strokewidth", str(sw)]
    for x0, y0, x1, y1 in boxes:
        cmd += ["-draw", f"rectangle {x0 * W:.0f},{y0 * H:.0f},{x1 * W:.0f},{y1 * H:.0f}"]
    subprocess.run(cmd + ["-quality", "90", dst], check=True)
    return True


def wgs84_to_sjtsk(lat, lon):
    """WGS84 → S-JTSK (EPSG:5514, záporné východ/sever) – Helmert na Bessel + Křovák (EPSG 9819), přesnost ~1 m.
    Jen pro odkaz do aplikace ČÚZK Archiv, která chce výřez v S-JTSK."""
    from math import radians, sin, cos, tan, asin, atan, sqrt, pi
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    p, l = radians(lat), radians(lon)
    N = a / sqrt(1 - e2 * sin(p) ** 2)
    x, y, z = N * cos(p) * cos(l), N * cos(p) * sin(l), N * (1 - e2) * sin(p)
    rx, ry, rz = (radians(s / 3600) for s in (4.9984, 1.5867, 5.2611))   # EPSG:1623 obráceně
    m = 1 - 3.5623e-6
    x, y, z = x - 570.8, y - 85.7, z - 462.8
    x, y, z = m * (x + rz * y - ry * z), m * (-rz * x + y + rx * z), m * (ry * x - rx * y + z)
    a, f = 6377397.155, 1 / 299.1528128
    e2 = f * (2 - f)
    pr = sqrt(x * x + y * y)
    p = atan(z / (pr * (1 - e2)))
    for _ in range(6):
        p = atan((z + e2 * a / sqrt(1 - e2 * sin(p) ** 2) * sin(p)) / pr)
    l = atan(y / x)
    e = sqrt(e2)
    pc, l0, ac, pp, kp = radians(49.5), radians(24 + 50 / 60), radians(30 + 17 / 60 + 17.30311 / 3600), radians(78.5), 0.9999
    A = a * sqrt(1 - e2) / (1 - e2 * sin(pc) ** 2)
    B = sqrt(1 + e2 * cos(pc) ** 4 / (1 - e2))
    g0 = asin(sin(pc) / B)
    t0 = tan(pi / 4 + g0 / 2) * ((1 + e * sin(pc)) / (1 - e * sin(pc))) ** (e * B / 2) / tan(pi / 4 + pc / 2) ** B
    n, r0 = sin(pp), kp * A / tan(pp)
    U = 2 * (atan(t0 * tan(p / 2 + pi / 4) ** B / ((1 + e * sin(p)) / (1 - e * sin(p))) ** (e * B / 2)) - pi / 4)
    V = B * (l0 - l)
    T = asin(cos(ac) * sin(U) + sin(ac) * cos(U) * cos(V))
    D = asin(cos(U) * sin(V) / cos(T))
    r = r0 * tan(pi / 4 + pp / 2) ** n / tan(T / 2 + pi / 4) ** n
    return -r * sin(n * D), -r * cos(n * D)


def cuzk_archiv(lat, lon, r=300):
    """Odkaz do ČÚZK Archiv (císařské otisky stabilního katastru 1824–1843) na výřez kolem bodu."""
    x, y = wgs84_to_sjtsk(lat, lon)
    return f"https://ags.cuzk.gov.cz/archiv/?extentstring={x - r:.0f},{y - r:.0f},{x + r:.0f},{y + r:.0f}"


EVENT_KINDS = {"*": "narození", "×": "sňatek", "†": "úmrtí"}
YEAR = re.compile(r"\b(1[3-9]\d\d|20[0-2]\d)\b")
CP = r"\w*\s*,?\s*(?:čp\.|č\.\s*p\.|č\.)\s*(?P<cp>\d+)"   # za názvem obce: „Holice čp. 112“, „v Rovni č. p. 7“


def timeline(people):
    """Narození, sňatky a úmrtí předků s rokem; sňatek manželů jen jednou."""
    out = {}
    for p in people.values():
        for f in p["facts"]:
            kind, y = f[:1], YEAR.search(f)
            if kind not in EVENT_KINDS or not y:
                continue
            who = frozenset([p["slug"], p["spouse"]]) if kind == "×" and p["spouse"] else frozenset([p["slug"]])
            key = (kind, y.group(1), who)
            if key in out:
                out[key]["people"].append(p["slug"])
                continue
            text = f[1:].strip()
            out[key] = dict(year=int(y.group(1)), date=text[:YEAR.search(text).end()], kind=kind, kindName=EVENT_KINDS[kind],
                            text=text, people=[p["slug"]], line=p["line"])
    return sorted(out.values(), key=lambda e: (e["year"], e["kind"] != "*"))


def houses(people, mista):
    """Domy podle čísel popisných ve faktech („Holice čp. 112“); poloha z mista.json → domy, jinak střed obce."""
    out = {}
    for name, e in mista.items():
        if "lat" not in e:
            continue
        rx = re.compile(r"(?:" + (e.get("re") or re.escape(name)) + r")" + CP)
        for p in people.values():
            for f in p["facts"]:
                for m in rx.finditer(f):
                    cp = m.group("cp")   # pojmenovaná: výraz re obce může mít vlastní skupiny
                    pos = (e.get("domy") or {}).get(cp)
                    h = out.setdefault((name, cp), dict(slug=slugify(f"{name} {cp}"), place=name, cp=cp, people=[],
                                                        exact=bool(pos), lat=pos[0] if pos else e["lat"], lon=pos[1] if pos else e["lon"]))
                    y = YEAR.search(f)
                    kind = f[:1] if f[:1] in EVENT_KINDS else ""
                    if not any(r["slug"] == p["slug"] and r["text"] == f for r in h["people"]):
                        h["people"].append(dict(slug=p["slug"], kind=kind, kindName=EVENT_KINDS.get(kind, "zmínka"),
                                                year=int(y.group(1)) if y else None, text=f))
    for h in out.values():
        h["people"].sort(key=lambda r: r["year"] or 9999)
        ys = [r["year"] for r in h["people"] if r["year"]]
        h["years"] = [min(ys), max(ys)] if ys else None
        h["cuzk"] = None if zeme(mista.get(h["place"], {})) == "cizina" else cuzk_archiv(h["lat"], h["lon"], 300 if h["exact"] else 900)
    return sorted(out.values(), key=lambda h: (h["place"], int(h["cp"])))


# Země podle kraje a okresu z OpenStreetMap (mista.json → osm). Okresy přes zemskou hranici (Svitavy, Žďár, Jihlava,
# Jindřichův Hradec, Frýdek-Místek, Ostrava) vrací None = neznámo; přesně jde zapsat "zeme" k obci v mista.json.
CECHY_KRAJE = ("Praha", "Středočeský", "Jihočeský", "Plzeňský", "Karlovarský", "Ústecký", "Liberecký", "Královéhradecký", "Pardubický", "Vysočina")
MORAVA_KRAJE = ("Jihomoravský", "Zlínský", "Olomoucký", "Moravskoslezský")
OKRESY = {"Svitavy": None, "Žďár nad Sázavou": None, "Jihlava": None, "Jindřichův Hradec": None, "Frýdek-Místek": None,
          "Ostrava-město": None, "Třebíč": "Morava", "Jeseník": "Slezsko", "Opava": "Slezsko", "Karviná": "Slezsko",
          "Bruntál": "Slezsko", "Nový Jičín": "Morava"}


def zeme(e):
    if e.get("zeme"):
        return e["zeme"]
    osm = e.get("osm", "")
    if osm and "Česko" not in osm:
        return "cizina"   # mimo Česko: české zemské události ani ČÚZK se jí netýkají
    okres = re.search(r"okres ([^,]+)", osm)
    if okres and okres.group(1).strip() in OKRESY:
        return OKRESY[okres.group(1).strip()]
    if any(k in osm for k in MORAVA_KRAJE):
        return "Morava"
    if any(k in osm for k in CECHY_KRAJE):
        return "Čechy"
    return None


def km(a, b):
    from math import radians, sin, cos, asin, sqrt
    la1, lo1, la2, lo2 = map(radians, (a[0], a[1], b[0], b[1]))
    return 12742 * asin(sqrt(sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2))


def dejiny(places, mista, udalosti):
    """Dějinné události, které se týkají obcí předků: místem (země, okruh, jmenované obce) i časem (kdy tam rod žil)."""
    out = []
    for u in udalosti:
        hits = []
        for pl in places:
            if pl["hypothesis"]:
                continue
            y = pl["years"]
            if y and not (y[0] - 30 <= u["do"] and u["od"] <= y[1] + 5):   # rod tam v té době (zhruba) žil
                continue
            if "mista" in u:
                d = 0 if pl["name"] in u["mista"] else None
            elif "kruh" in u:
                ds = [km((pl["lat"], pl["lon"]), k[:2]) for k in u["kruh"] if km((pl["lat"], pl["lon"]), k[:2]) <= k[2]]
                d = min(ds) if ds else None
            else:
                z = zeme(mista.get(pl["name"], {}))
                d = 0 if z is None or z in u.get("zeme", []) else None
            if d is not None:
                hits.append((d, pl["name"]))
        if hits:
            hits.sort()
            out.append(dict(od=u["od"], do=u["do"], nazev=u["nazev"], text=u["text"], wiki=u.get("wiki"),
                            mistni="kruh" in u or "mista" in u, mista=[n for _, n in hits][:6], km=round(hits[0][0]) if "kruh" in u else None))
    return sorted(out, key=lambda e: e["od"])


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def login_files(cfg):
    """Přihlašovací brána: otázka na webu, na serveru (nginx i Netlify) jen otisk odpovědi (SHA-256).
    Stejný otisk spočítá přihlašovací stránka a uloží ho do cookie – samotná odpověď se nikam neukládá."""
    login = cfg.get("prihlaseni") or {}
    answer = norm_answer(login.get("odpoved", ""))
    tpl = open(os.path.join(WEB, "prihlaseni.sablona.html"), encoding="utf-8").read()
    if "rodokmen:" not in tpl:   # stará šablona (do 0.4.0) ukládá do cookie odpověď – s novou bránou by se nikdo nepřihlásil
        sys.exit("CHYBA: web/ má starou šablonu přihlášení. Aktualizujte projekt: python3 -I <skill>/tools/novy_projekt.py <složka projektu>")
    contact = cfg.get("kontakt") or {}
    hint = ""
    if contact.get("email"):
        hint = (f'Neznáte odpověď? Napište {html.escape(contact.get("jmeno", ""))} na '
                f'<a href="mailto:{html.escape(contact["email"])}">{html.escape(contact["email"])}</a>.')
    page = (tpl.replace("{{NAZEV}}", html.escape(cfg.get("nazev", "Rodokmen")))
               .replace("{{UVOD}}", html.escape(login.get("uvod", "Tenhle web je jen pro rodinu a příbuzné.")))
               .replace("{{OTAZKA}}", html.escape(login.get("otazka", "Odpověď na rodinnou otázku")))
               .replace("{{NAPOVEDA}}", hint))
    write(os.path.join(WEB, "public", "prihlaseni.html"), page)

    edge = os.path.join(WEB, "netlify", "edge-functions", "brana.js")
    if answer:
        digest = hashlib.sha256(("rodokmen:" + answer).encode()).hexdigest()
        nginx_map = f'  "{digest}" 1;'
        write(edge, open(os.path.join(WEB, "netlify", "brana.sablona.js"), encoding="utf-8").read().replace("{{HASH}}", digest))
    else:   # bez přihlášení – web je otevřený
        nginx_map = "  default 1;"
        if os.path.exists(edge):
            os.remove(edge)
    nginx = open(os.path.join(WEB, "nginx.sablona.conf"), encoding="utf-8").read()
    if not answer:   # otevřený web: default 0 v mapě přihlášení nahradí default 1 (dva default nginx odmítne)
        nginx = re.sub(r"(map \$cookie_rodokmen \$rodokmen_ok \{.*?)\n *default 0;", r"\1", nginx, count=1, flags=re.S)
    nginx = nginx.replace("{{ODPOVED}}", nginx_map)
    write(os.path.join(WEB, "nginx.conf"), nginx)
    cloudflare_files(cfg, digest if answer else "")
    return bool(answer)


def cloudflare_files(cfg, digest):
    """Brána pro Cloudflare (web/cloudflare/worker.js) a web/wrangler.jsonc pro `npm run nasadit-cloudflare`."""
    tpl = os.path.join(WEB, "cloudflare", "worker.sablona.js")
    if not os.path.exists(tpl):
        return
    # cloudflare.nazev = subdoména účtu (adresa https://rodokmen.<nazev>.workers.dev), zakládá ji nasadit_cloudflare.mjs
    name = ((cfg.get("cloudflare") or {}).get("nazev") or "").strip()
    if name and not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,48}[a-z0-9])?", name):
        sys.exit(f"CHYBA: cloudflare.nazev v data/web.json „{name}“ nejde použít – jen malá písmena bez diakritiky, "
                 "číslice a pomlčky (nejvýš 50 znaků), např. „novakovi“.")
    worker = (open(tpl, encoding="utf-8").read().replace("{{HASH}}", digest)
              .replace("{{OTEVRENY}}", "false" if digest else "true"))
    write(os.path.join(WEB, "cloudflare", "worker.js"), worker)
    wrangler = {
        "name": "rodokmen",
        "main": "cloudflare/worker.js",
        "compatibility_date": "2026-10-01",
        "workers_dev": True,      # adresa https://rodokmen.<subdoména>.workers.dev
        "preview_urls": False,    # bez zvláštních adres pro jednotlivé verze
        "assets": {"directory": "./dist", "binding": "ASSETS", "run_worker_first": True,
                   "not_found_handling": "404-page"},
    }
    write(os.path.join(WEB, "wrangler.jsonc"),
          "// Vyrábí tools/export_web.py – ručně neupravovat. Nasazení: npm run nasadit-cloudflare.\n"
          + json.dumps(wrangler, ensure_ascii=False, indent=2) + "\n")


def main():
    ns = load_people()
    P, LINES, SIDE, ISSUES = ns["P"], ns["LINES"], ns["SIDE"], ns["ISSUES"]
    if 1 not in P:
        sys.exit("V data/osoby.py chybí výchozí osoba (číslo 1).")
    SAME = ns["SAME"]                       # alias Kekulé → kanonické Kekulé (předek v rodokmenu vícekrát)
    cfg = jload("web.json", {})
    login = cfg.get("prihlaseni") or {}
    if "--nasazeni" in sys.argv and not norm_answer(login.get("odpoved", "")) and not login.get("otevreny"):
        if login.get("odpoved", "").strip():
            sys.exit("CHYBA: odpověď na přihlašovací otázku musí obsahovat písmena nebo číslice z latinky "
                     "(azbuka a samotné symboly nejdou, diakritika nevadí). Zvolte s uživatelem jinou odpověď.")
        sys.exit("CHYBA: v data/web.json není odpověď na přihlašovací otázku – web by byl otevřený komukoli.\n"
                 "Nastavte prihlaseni.odpoved, nebo (jen když to opravdu chcete) prihlaseni.otevreny: true.")
    docs_cfg = jload("dokumenty.json", [])
    recs = {r["key"]: r for r in record_rows()}

    slugs, used = {}, set()
    for k in sorted(P):
        p = P[k]
        if placeholder(p) or k in SAME:
            continue
        yv = (p.get("y") or "").strip()
        ys = [] if yv.startswith(("?", "†")) else re.findall(r"\d{4}", yv)   # rok úmrtí do adresy nedávat
        s = slugify(p["n"] + (" " + ys[0] if ys else ""))
        if s in used or not s:
            s = f"{s}-{k}"
        used.add(s)
        slugs[k] = s
    for a, c in SAME.items():
        slugs[a] = slugs[c]
    aliases_of = {}
    for a, c in SAME.items():
        aliases_of.setdefault(c, []).append(a)

    def line_of(k):
        g = gen(k)
        return k >> (g - 3) if g >= 3 else None

    people = {}
    for k, p in sorted(P.items()):
        if k not in slugs or k in SAME:
            continue
        path, c = [], k
        while c >= 1:
            path.append(slugs.get(c))
            c //= 2
        people[slugs[k]] = dict(
            k=k, slug=slugs[k], name=p["n"], y=p.get("y", ""), years=years(p.get("y")), st=p.get("st", "unk"),
            status=STATUS.get(p.get("st"), ""), gen=gen(k), sex="M" if k == 1 and p.get("sex", "M") == "M" or k > 1 and k % 2 == 0 else "F",
            rel=relation(k), line=line_of(k), facts=p.get("f", []), note=p.get("note", ""), records=[r for r in p.get("r", []) if r in recs],
            father=slugs.get(2 * k), mother=slugs.get(2 * k + 1),
            fatherUnknown=(2 * k in P and placeholder(P[2 * k])), motherUnknown=(2 * k + 1 in P and placeholder(P[2 * k + 1])),
            child=slugs.get(k // 2) if k > 1 else None, spouse=slugs.get(k ^ 1) if k > 1 else None,
            family=None, ownFamily=None, path=path,
            side=[dict(name=s["n"], text=s["t"], records=[r for r in s.get("r", []) if r in recs]) for s in SIDE if s["k"] == k],
            docs=[dict(img=d["img"], caption=d["popis"]) for d in docs_cfg if k in d.get("osoby", [])],
            children=[slugs[c] for c in [k // 2] + [a // 2 for a in aliases_of.get(k, [])] if k > 1 and c in slugs],
            also=[dict(k=a, rel=relation(a), line=line_of(a), child=slugs.get(a // 2)) for a in aliases_of.get(k, [])],
        )
        if aliases_of.get(k):
            for a in aliases_of[k]:
                people[slugs[k]]["records"] = list(dict.fromkeys(people[slugs[k]]["records"] + [r for r in P[a].get("r", []) if r in recs]))
            people[slugs[k]]["facts"] = [f for f in people[slugs[k]]["facts"] if not f.startswith("TÁŽ OSOBA")]

    families = {}
    for k in sorted(P):
        f, m = 2 * k, 2 * k + 1
        if k not in slugs or k in SAME or (f not in slugs and m not in slugs):
            continue
        fs, ms = slugs.get(f), slugs.get(m)
        fid = "-a-".join(x for x in (fs, ms) if x) if fs and ms else (fs or ms) + "-rodina"
        surname = (P[m]["n"].split()[-1] if m in P else "").strip("()?")
        mfacts = [x for x in P.get(f, {}).get("f", []) + P.get(m, {}).get("f", []) if x.startswith("×")]
        marriage = [x for x in mfacts if surname and surname[:5] in x] or mfacts
        frec = P.get(f, {}).get("r", []) + P.get(m, {}).get("r", [])
        child_rec = [r for r in P[k].get("r", []) if r in recs and recs[r]["kind"] == "N"]
        rlist = [r for r in dict.fromkeys(frec) if r in recs and recs[r]["kind"] == "O"] + child_rec
        if fid in families:   # stejný pár potkán dvakrát (předek v rodokmenu vícekrát) – jedna rodina, víc dětí
            fam = families[fid]
            fam["children"].append(slugs[k])
            fam["records"] = list(dict.fromkeys(fam["records"] + rlist))
            fam["side"] += people[slugs[k]]["side"]
        else:
            families[fid] = dict(id=fid, father=fs, mother=ms, fatherUnknown=f in P and placeholder(P[f]),
                                 child=slugs[k], children=[slugs[k]], marriage=marriage, records=rlist,
                                 line=line_of(f) if f in P else line_of(m), gen=gen(f), side=list(people[slugs[k]]["side"]))
        people[slugs[k]]["family"] = fid
        for x in (fs, ms):
            if x:
                people[x]["ownFamily"] = fid

    refs = {}
    for s, p in people.items():
        for r in p["records"] + [r for e in p["side"] for r in e["records"]]:
            refs.setdefault(r, []).append(s)
    hl = jload("zvyrazneni.json", {})
    prep = jload("prepisy.json", {})
    records = []
    for key, r in recs.items():
        r = dict(r)
        r["boxes"] = hl.get(key, {}).get("boxes", [])
        tr = prep.get(key, {})
        r["orig"], r["cs"] = tr.get("orig", ""), tr.get("cs", "")
        r["kindName"] = KINDS.get(r["kind"], r["kind"])
        r["people"] = list(dict.fromkeys(refs.get(key, [])))
        records.append(r)

    lines = {}
    for k, (name, desc) in sorted(LINES.items()):
        if k not in LINE_COLORS:
            continue
        members = [(p["k"], p) for p in people.values() if p["line"] == k]
        members += [(a["k"], p) for p in people.values() for a in p["also"] if a["line"] == k]
        members.sort(key=lambda x: x[0])
        lines[slugify(name)] = dict(k=k, slug=slugify(name), name=name, desc=desc, color=LINE_COLORS[k],
                                    root=slugs.get(k), people=[p["slug"] for _, p in members],
                                    gens={p["slug"]: gen(kk) for kk, p in members})
    lines = {s: l for s, l in lines.items() if l["root"]}
    for p in people.values():
        p["lineSlug"] = next((l["slug"] for l in lines.values() if l["k"] == p["line"]), None)

    places = []
    for name, e in jload("mista.json", {}).items():
        if "lat" not in e:
            continue
        rx = re.compile(e.get("re") or re.escape(name))
        hits = [p for p in people.values() if rx.search(" ".join(p["facts"]))]
        byline = {}
        for p in sorted(hits, key=lambda p: p["k"]):
            byline.setdefault(p["line"] or 0, []).append(p["slug"])
        if e.get("hypoteza"):
            byline = {e.get("rod", 0): []}
        if not byline:
            continue
        yrs = [int(y) for p in hits for y in re.findall(r"\b1[4-9]\d\d\b", p["y"] or "")]
        places.append(dict(name=name, lat=e["lat"], lon=e["lon"], lines=[dict(k=k, people=v) for k, v in sorted(byline.items())],
                           years=[min(yrs), max(yrs)] if yrs else None, hypothesis=bool(e.get("hypoteza"))))

    known = [p for p in people.values() if p["k"] > 1]
    stats = dict(ancestors=len(known), documented=sum(p["st"] == "doc" for p in known), records=len(records),
                 generations=max(p["gen"] for p in people.values()) + 1)
    hypotheses = [dict(line=h.get("rod"), title=h.get("nadpis", "Hypotéza"), text=h.get("text", ""),
                       items=[dict(name=a, text=b) for a, b in h.get("polozky", [])],
                       records=[r for r in h.get("zaznamy", []) if r in recs]) for h in ns["HYPOTEZY"]]

    has_story = os.path.exists(os.path.join(DATA, "pribeh.md"))
    public_cfg = {k: v for k, v in cfg.items() if k != "prihlaseni"}
    public_cfg["maPribeh"] = has_story
    mista = jload("mista.json", {})
    udalosti = json.load(open(os.path.join(TOOLS, "dejiny.json"), encoding="utf-8"))["udalosti"] \
        if os.path.exists(os.path.join(TOOLS, "dejiny.json")) else []
    udalosti += jload("dejiny.json", {}).get("udalosti", [])   # místní události projektu (požár, povodeň, kostel)
    site = dict(config=public_cfg, places=places, events=timeline(people), houses=houses(people, mista),
                eras=dejiny(places, mista, udalosti), root=slugs[1], aliases={a: slugs[a] for a in SAME}, people=people,
                families=families, records=records, lines=lines,
                issues=[dict(title=i, text="") if isinstance(i, str) else dict(title=i[0], text=i[1]) for i in ISSUES], stats=stats, hypotheses=hypotheses,
                docs=[dict(img=d["img"], caption=d["popis"], people=[slugs[k] for k in d.get("osoby", []) if k in slugs])
                      for d in docs_cfg if os.path.exists(os.path.join(VYREZY, d["img"] + ".jpg"))])

    write(os.path.join(WEB, "src", "data", "site.json"), json.dumps(site, ensure_ascii=False, indent=1))
    gen_dir = os.path.join(WEB, "src", "generated")
    for src, dst in (("archivni_dotazy.md", "dotazy.md"), ("research_log.md", "denik.md"), ("zajimavosti.md", "zajimavosti.md")):
        path = os.path.join(DATA, src)
        text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        write(os.path.join(gen_dir, dst), strip_comments(re.sub(r"^# .*\n", "", text, count=1)))
    story = os.path.join(DATA, "pribeh.md")
    write(os.path.join(gen_dir, "pribeh.md"), strip_comments(open(story, encoding="utf-8").read()) if has_story else "---\ntitle: Příběh\nlead: ''\n---\n")

    hrefs = os.path.join(gen_dir, "fan_hrefs.json")
    json.dump({k: f"/osoba/{s}/" for k, s in slugs.items()}, open(hrefs, "w", encoding="utf-8", newline="\n"))
    subprocess.run([sys.executable, "-I", "-X", "utf8", os.path.join(TOOLS, "fan_chart.py"),
                    os.path.join(gen_dir, "fan.svg"), "--web", hrefs], check=True, capture_output=True)

    gated = login_files(cfg)

    copied = 0
    zv = os.path.join(DATA, "zvyrazneni.json")
    hl_mtime = os.path.getmtime(zv) if os.path.exists(zv) else 0
    for sub, src_dir in (("img", VYREZY), ("zdroje", ZDROJE)):
        dst_dir = os.path.join(WEB, "public", sub)
        os.makedirs(dst_dir, exist_ok=True)
        for key in list(recs) + [d["img"] for d in docs_cfg] + ([cfg["uvod"]["foto"]] if cfg.get("uvod", {}).get("foto") else []):
            src = os.path.join(src_dir, key + ".jpg")
            dst = os.path.join(dst_dir, key + ".jpg")
            if not os.path.exists(src):
                continue
            boxes = hl.get(key, {}).get("boxes", [])
            stale = not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst) \
                or (sub == "zdroje" and boxes and hl_mtime > os.path.getmtime(dst))
            if not stale:
                continue
            if sub == "zdroje" and boxes and draw_boxes(src, dst, boxes, os.path.join(VYREZY, key + ".jpg")):
                copied += 1
                continue
            shutil.copy2(src, dst)
            copied += 1
    print(f"{len(people)} osob, {len(families)} rodin, {len(records)} zápisů, {len(lines)} rodů, {len(places)} míst; "
          f"zkopírováno {copied} obrázků; přihlášení {'zapnuté' if gated else 'VYPNUTÉ (web je otevřený)'}")

    # odkazy v textech, které nikam nevedou (adresa osoby se změní třeba doplněním roku narození: jan-novak → jan-novak-1798)
    targets = dict(osoba=people, zdroj=recs, rod=lines, rodina=families)
    texts = {f: open(os.path.join(gen_dir, f), encoding="utf-8").read() for f in ("pribeh.md", "zajimavosti.md")}
    texts["web.json"] = json.dumps(cfg, ensure_ascii=False)
    texts["osoby.py (hypotézy)"] = json.dumps(hypotheses, ensure_ascii=False)
    broken = [(f, m.group(0)) for f, t in texts.items()
              for m in re.finditer(r"/(osoba|zdroj|rod|rodina)/([^/\s)\"'#?<>\]]+)", t) if m.group(2) not in targets[m.group(1)]]
    for f, link in dict.fromkeys(broken):
        print(f"POZOR: nefunkční odkaz {link}/ v {f} – oprav ho (adresy stránek jsou ve web/src/data/site.json)")


if __name__ == "__main__":
    main()
