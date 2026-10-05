"""Lecture de la veille quotidienne du pipeline Claude cowork.

Le pipeline écrit chaque matin `Veille quotidienne/<YYYY-MM-DD>/Compte
rendu.md` dans JOB_SEARCH_DIR. On en extrait, sans toucher aux fichiers :
les offres retenues (champs, grille, liens typés), les offres écartées, les
notes d'en-tête et la conclusion.

Le format a changé plusieurs fois depuis juillet 2026 : « Salaire affiché »
puis « Salaire », un titre coupé par un tiret, puis par une virgule, puis
par un tiret long. Les anciens intitulés restent reconnus, pour que
l'historique reste lisible. Ce qui n'est pas reconnu n'est jamais perdu : il
s'affiche tel quel.
"""
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from flask import current_app

MONTHS_FR = [None, "janvier", "février", "mars", "avril", "mai", "juin",
             "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

# Les cinq familles de rôles des instructions de la tâche (version du
# 5 octobre 2026). Libellés courts : ils vivent dans des pastilles.
FAMILIES = {
    "A": "Cadrage produit",
    "B": "Avant-vente",
    "C": "IA appliquée",
    "D": "Qualité des données",
    "E": "Relations développeurs",
}
CRITERIA = ["métier", "environnement", "apprentissage", "sens", "faisabilité"]
_LEVELS = {"fort": 3, "forte": 3, "moyen": 2, "moyenne": 2, "faible": 1}

# Un titre de niveau 2, pas de niveau 3 : « ### » commence aussi par « ## ».
_H2_SPLIT_RE = re.compile(r"^##(?!#)[ \t]*(.+?)[ \t]*$", re.M)
_LINK_RE = re.compile(r"https?://[^\s)>\]]+")
# « - **Clé** : valeur », avec les deux-points tantôt dans le gras, tantôt
# après ; à la mi-septembre, un point dans le gras (« **Entreprise.** »).
# Exiger l'un des deux évite de prendre pour une rubrique une phrase qui
# commence simplement en gras. Une rubrique peut aussi être une ligne
# entière en gras, suivie d'une liste.
_FIELD_RE = re.compile(r"^\s*[-*]\s+\*\*([^*]+?)\s*(?:[:.]\s*\*\*|\*\*\s*:)\s*(.*)$")
_RUBRIC_RE = re.compile(r"^\*\*([^*]+?)\s*(?:[:.]\s*\*\*|\*\*\s*:|\*\*\s*$)\s*(.*)$")
_RANK_RE = re.compile(r"^(\d+)\.\s*")
_BEST_RE = re.compile(r"\s*\(meilleur fit[^)]*\)\s*$", re.I)
_GRID_RE = re.compile(r"(m[ée]tier|environnement|apprentissage|sens|faisabilit[ée])"
                      r"\s*:?\s*(forte?|moyen(?:ne)?|faible)", re.I)
_SPLIT_RE = re.compile(r"«?\s*Vues\s*:\s*([^.»\n]*)\.?\s*"
                       r"Retenues\s*:\s*([^.»\n]*)\.?\s*»?", re.I)
_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")

_FIELDS = {
    "famille": "family", "verdict": "verdict", "grille": "grid",
    "publiee le": "published", "publiee": "published",
    "publication": "published", "date de publication": "published",
    "salaire": "salary", "salaire affiche": "salary",
    "experience": "experience", "experience demandee": "experience",
    "cv": "cv", "cv a joindre": "cv", "cv recommande": "cv",
    "entreprise": "company", "lieu": "location", "localisation": "location",
    "contrat et lieu": "location", "lieu et contrat": "location",
    "lieu / contrat": "location",
}
_RUBRICS = {
    "fit": "fit", "fit honnete": "fit",
    "ce que j'ai trouve sur eux": "research",
    "l'angle": "angle",
    "la question a poser": "question",
    "verifier que l'offre est toujours active": "links",
    "candidature": "links",
}


def _key(text):
    """« Ce que j’ai trouvé sur eux : » -> « ce que j'ai trouve sur eux »."""
    text = text.replace("’", "'").strip().rstrip(":").strip().lower()
    return "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))


def cap(text):
    """Majuscule initiale : la rubrique suit « **Fit** : », d'où « un PO qui ».

    Seulement si le texte commence par une lettre : « 2 à 4 ans » ne doit
    pas devenir « 2 À 4 ans ».
    """
    for i, c in enumerate(text):
        if c.isalnum():
            return text[:i] + c.upper() + text[i + 1:] if c.isalpha() else text
    return text


def _links_note(text):
    """La rubrique des liens, si elle dit autre chose que « Plateforme : URL ».

    Les anciens comptes rendus y glissaient des remarques qui comptent
    (« tu as déjà candidaté chez eux en mai ») : les boutons ne les montrent
    pas, on les garde donc à lire.
    """
    for line in text.splitlines():
        rest = _LINK_RE.sub("", line)
        rest = re.sub(r"^\s*[-*]?\s*[^:]{0,40}:", "", rest, count=1)
        if len(re.sub(r"[\W_]+", "", rest)) > 20:
            return text
    return ""


def date_fr(d):
    label = f"{DAYS_FR[d.weekday()]} {d.day} {MONTHS_FR[d.month]} {d.year}"
    return label[0].upper() + label[1:]


def _split_title(title):
    """Sépare intitulé et entreprise.

    Le tiret long gagne quand il est là. Sinon la première virgule : dans
    « Poste, Entreprise, service », ce qui la suit est l'entreprise puis son
    service. Le tiret court ne vient qu'en dernier, parce qu'il apparaît
    aussi dans les intitulés (« CDI - AI Product Manager »).
    """
    if " — " in title:
        role, company = title.rsplit(" — ", 1)
    elif ", " in title:
        role, company = title.split(", ", 1)
    elif " - " in title:
        role, company = title.rsplit(" - ", 1)
    else:
        role, company = title, ""
    return role.strip(), company.strip()


def _published(raw, ref):
    """Date de publication lue dans « 30/09 », « 30/09/2026 », « hier »...

    `ref` est le jour du compte rendu : c'est à lui que « hier » se rapporte.
    """
    if not raw:
        return None
    m = _DATE_RE.search(raw)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else ref.year
        year += 2000 if year < 100 else 0
        try:
            found = date(year, month, day)
            # « 28/12 » lu dans le compte rendu du 2 janvier
            if not m.group(3) and found > ref + timedelta(days=1):
                found = found.replace(year=year - 1)
        except ValueError:
            return None
        return found
    low = _key(raw)
    if "aujourd'hui" in low or "ce matin" in low or re.search(r"\d+\s*h(eure)?", low):
        return ref
    if "hier" in low or "la veille" in low:
        return ref - timedelta(days=1)
    m = re.search(r"il y a (\d+)\s*j", low)
    return ref - timedelta(days=int(m.group(1))) if m else None


def _host(url):
    host = urlparse(url).netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    # « noveocare.taleez.com » -> « taleez.com » : c'est la plateforme qui
    # dit où l'on va postuler, l'entreprise est déjà dans le titre.
    return ".".join(host.split(".")[-2:])


def _actions(links_text, body):
    """Liens typés : « offer » pour lire l'annonce, « apply » pour postuler.

    La rubrique « Vérifier que l'offre est toujours active » les nomme
    (« Plateforme : », « Candidature directe : »). Sans elle, on retombe sur
    toutes les URL du texte, comme avant.
    """
    actions, seen = [], set()

    def add(kind, url):
        url = url.rstrip(".,;:!?*»\"'")
        # Un bouton par plateforme et par usage : deux « Voir l'offre »
        # vers le même site ne disent rien de plus que le premier.
        if (kind, _host(url)) in seen or len(actions) >= 4:
            return
        seen.add((kind, _host(url)))
        actions.append({"kind": kind, "url": url, "host": _host(url)})

    for line in (links_text or "").splitlines():
        low = _key(line)
        kind = "apply" if ("candidature" in low or "postuler" in low) else "offer"
        for url in _LINK_RE.findall(line):
            add(kind, url)
    if not actions:
        for url in _LINK_RE.findall(body):
            add("apply" if ("apply" in url or "ats." in url) else "offer", url)
    return actions


def _parse_offer(block, ref, today):
    lines = block.strip().splitlines()
    if not lines:
        return None
    head = lines[0].strip()
    rank = _RANK_RE.match(head)
    title = _RANK_RE.sub("", head).strip()
    body = "\n".join(lines[1:]).strip()

    # Les puces « - **Clé** : valeur » du haut sont des champs ; ensuite,
    # chaque « **Rubrique** : » ouvre une rubrique qui court jusqu'à la
    # suivante, listes comprises.
    fields, other_fields, rubrics, intro = {}, [], [], []
    current = None
    for line in lines[1:]:
        r = _RUBRIC_RE.match(line)
        if r:
            key = _key(r.group(1))
            if key in _FIELDS and _FIELDS[key] not in fields:
                fields[_FIELDS[key]] = r.group(2).strip()
                current = None
                continue
            current = {"key": key, "label": r.group(1).strip(), "lines": [r.group(2)]}
            rubrics.append(current)
            continue
        f = _FIELD_RE.match(line)
        if f and current is None:
            kind = _FIELDS.get(_key(f.group(1)))
            if kind and kind not in fields:
                fields[kind] = f.group(2).strip()
            else:
                other_fields.append({"label": f.group(1).strip(),
                                     "value": f.group(2).strip()})
            continue
        (intro if current is None else current["lines"]).append(line)

    sections, other_sections = {}, []
    for r in rubrics:
        text = cap("\n".join(r["lines"]).strip())
        kind = _RUBRICS.get(r["key"])
        if kind and kind not in sections:
            sections[kind] = text
        elif text:
            other_sections.append({"label": r["label"], "text": text})
    intro_text = "\n".join(intro).strip()
    if intro_text:
        other_sections.insert(0, {"label": "", "text": intro_text})

    best = bool(_BEST_RE.search(title))
    role, company = _split_title(_BEST_RE.sub("", title).strip())
    named = fields.get("company")
    if named:
        # Le champ « Entreprise » tranche quand l'intitulé contient lui-même
        # une virgule (« Finance, Content et Business, CANAL+ Group »).
        for sep in (", ", " — ", " - "):
            if title.endswith(sep + named):
                role, company = title[:-len(sep + named)].strip(), named
                break
        else:
            company = company or named

    family = None
    m = re.match(r"\s*([A-E])\b", fields.get("family", ""))
    if m:
        family = {"letter": m.group(1), "label": FAMILIES[m.group(1)]}

    verdict = None
    if fields.get("verdict"):
        v = _key(fields["verdict"])
        verdict = {"label": fields["verdict"].strip().rstrip("."),
                   "kind": "go" if v.startswith("postuler")
                   else "maybe" if "considerer" in v else ""}

    found = {_key(name): word.lower()
             for name, word in _GRID_RE.findall(fields.get("grid", ""))}
    grid = [{"name": c.capitalize(), "word": found[_key(c)],
             "level": _LEVELS[found[_key(c)]]}
            for c in CRITERIA if _key(c) in found]

    published = _published(fields.get("published"), ref)
    age = (today - published).days if published else None

    return {
        # Clés historiques, lues telles quelles par l'ESP32 et Jarvis.
        "title": title,
        "body": body,
        "links": _LINK_RE.findall(body),
        "rank": int(rank.group(1)) if rank else None,
        "role": role,
        "company": company,
        "best": best,
        "family": family,
        "verdict": verdict,
        "grid": grid,
        "published": published,
        "published_raw": fields.get("published", ""),
        "age_days": age,
        "salary": fields.get("salary", ""),
        "experience": fields.get("experience", ""),
        "cv": fields.get("cv", ""),
        "location": fields.get("location", ""),
        "other_fields": other_fields,
        "sections": sections,
        "other_sections": other_sections,
        "actions": _actions(sections.get("links"), body),
        "links_note": _links_note(sections.get("links", "")),
    }


def _preamble(text):
    """En-tête du compte rendu : alertes (citations), sources, notes."""
    alerts, kept, quote = [], [], []
    for line in text.splitlines():
        if re.match(r"^#\s", line):          # le titre « # Veille du ... »
            continue
        if line.lstrip().startswith(">"):
            quote.append(line.lstrip()[1:].strip())
            continue
        if quote:
            alerts.append(" ".join(q for q in quote if q))
            quote = []
        kept.append(line)
    if quote:
        alerts.append(" ".join(q for q in quote if q))
    notes = re.sub(r"^\s*-{3,}\s*$", "", "\n".join(kept), flags=re.M).strip()

    sources = ""
    m = re.search(r"^(?:\*\*)?Sources?\s+(?:utilisées?|principale)\s*"
                  r"(?::\s*\*\*|\*\*\s*:|:)\s*(.+)$", notes, re.M | re.I)
    # Une valeur qui garde un « ** » orphelin vient d'une phrase entière
    # mise en gras : on la laisse dans les notes plutôt que de l'abîmer.
    if m and m.group(1).count("**") % 2 == 0:
        sources = m.group(1).strip()
        notes = (notes[:m.start()] + notes[m.end():]).strip()
    return sources, [a for a in alerts if a], notes


def _conclusion(text):
    """Conclusion sans la répartition par famille, qui devient un graphique."""
    split = None
    m = _SPLIT_RE.search(text)
    if m:
        def counts(s):
            return {k: int(v) for k, v in re.findall(r"\b([A-E])\s*:?\s*(\d+)", s)}
        split = {"seen": counts(m.group(1)), "kept": counts(m.group(2))}
        text = text[:m.start()] + text[m.end():]
    text = re.sub(r"«?\s*Les lettres de motivation se demandent à la carte\.?\s*»?",
                  "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip(), split


def parse_report(text, day, dirname):
    today = date.today()
    ref = day or today
    parts = _H2_SPLIT_RE.split(text)
    preamble, pairs = parts[0], list(zip(parts[1::2], parts[2::2]))

    offers, rejected, extras, conclusion = [], [], [], ""
    for title, body in pairs:
        key = _key(title)
        if key.startswith("offres retenues"):
            for block in re.split(r"^###\s+", body, flags=re.M)[1:]:
                offer = _parse_offer(block, ref, today)
                if offer:
                    offers.append(offer)
        elif key == "conclusion":
            conclusion = body.strip()
        elif "ecart" in key:
            rejected.append(body.strip())
        elif key.startswith("source"):
            preamble += "\n\n**Source utilisée** : " + body.strip()
        elif body.strip():
            extras.append({"title": title.strip(), "text": body.strip()})

    sources, alerts, notes = _preamble(preamble)
    conclusion, split = _conclusion(conclusion)
    rejected_text = "\n\n".join(r for r in rejected if r)
    return {
        "date": day,
        "dirname": dirname,
        "date_fr": date_fr(day) if day else dirname,
        "day_short": f"{DAYS_FR[day.weekday()][:3]}. {day.day}" if day else dirname,
        "is_today": day == today if day else False,
        "offers": offers,
        "sources": sources,
        "alerts": alerts,
        "notes": notes,
        "rejected": rejected_text,
        "rejected_count": len(re.findall(r"^[-*]\s+", rejected_text, re.M)),
        "extras": extras,
        "conclusion": conclusion,
        "split": split,
        "raw": text,
    }


def letters_dir():
    root = current_app.config.get("JOB_SEARCH_DIR") or ""
    base = Path(root) / "Lettres de motivation"
    return base if root and base.is_dir() else None


def get_cover_letters():
    """Lettres de motivation générées par le pipeline, plus récentes d'abord.

    Renvoie None si le dossier n'est pas configuré/trouvé. Les fichiers
    préfixés par « _ » (templates) sont ignorés.
    """
    base = letters_dir()
    if base is None:
        return None
    letters = []
    for f in base.iterdir():
        if not f.is_file() or f.name.startswith("_"):
            continue
        stat = f.stat()
        letters.append({
            "filename": f.name,
            "title": f.stem,
            "ext": f.suffix.lstrip(".").lower(),
            "readable": f.suffix.lower() in (".md", ".txt"),
            "mtime": datetime.fromtimestamp(stat.st_mtime),
            "size_kb": max(1, stat.st_size // 1024),
        })
    letters.sort(key=lambda x: x["mtime"], reverse=True)
    return letters


def read_cover_letter(filename):
    """Contenu d'une lettre .md/.txt, ou None si introuvable/interdit."""
    base = letters_dir()
    if base is None:
        return None
    target = (base / filename).resolve()
    if (not target.is_file() or target.suffix.lower() not in (".md", ".txt")
            or not target.is_relative_to(base.resolve())):
        return None
    return target.read_text(encoding="utf-8")


def _reports_dir():
    root = current_app.config.get("JOB_SEARCH_DIR") or ""
    base = Path(root) / "Veille quotidienne"
    return base if root and base.is_dir() else None


def _read(d):
    f = d / "Compte rendu.md"
    if not f.is_file():
        return None
    try:
        day = datetime.strptime(d.name, "%Y-%m-%d").date()
    except ValueError:
        day = None
    try:
        text = f.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_report(text, day, d.name)


def get_daily_reports(limit=14):
    """Comptes rendus des derniers jours, du plus récent au plus ancien.

    Renvoie None si JOB_SEARCH_DIR n'est pas configuré ou introuvable.
    """
    base = _reports_dir()
    if base is None:
        return None
    reports = []
    for d in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
        if not d.is_dir():
            continue
        report = _read(d)
        if report:
            reports.append(report)
        if len(reports) >= limit:
            break
    return reports


def get_report(dirname):
    """Un compte rendu précis, par son dossier AAAA-MM-JJ ; None sinon."""
    base = _reports_dir()
    if base is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dirname or ""):
        return None
    d = base / dirname
    return _read(d) if d.is_dir() else None


def freshness(reports, now=None):
    """Bandeau à afficher quand la veille du jour manque, sinon None.

    La tâche part à 9h et finit entre 9h05 et 13h environ ; la
    synchronisation la pousse ici dans la demi-heure. Avant 13h, un jour
    sans compte rendu est donc normal. Après, c'est qu'elle n'a pas tourné :
    si le PC ou l'app Claude étaient éteints à 9h, l'app suspend la tâche
    jusqu'à ce qu'on la réactive.
    """
    now = now or datetime.now()
    if not reports or reports[0]["date"] is None:
        return None
    last = reports[0]["date"]
    gap = (now.date() - last).days
    if gap <= 0:
        return None
    if gap == 1 and now.hour < 13:
        return {"kind": "info", "gap": gap, "last": reports[0]}
    return {"kind": "warn", "gap": gap, "last": reports[0]}


def family_totals(reports):
    """Vues et retenues par famille, cumulées sur les comptes rendus donnés.

    Seuls les comptes rendus au format du 5 octobre 2026 portent cette
    répartition : None tant qu'aucun ne l'a.
    """
    seen, kept, days = {}, {}, 0
    for r in reports:
        if not r["split"]:
            continue
        days += 1
        for k, v in r["split"]["seen"].items():
            seen[k] = seen.get(k, 0) + v
        for k, v in r["split"]["kept"].items():
            kept[k] = kept.get(k, 0) + v
    if not days:
        return None
    top = max(seen.values(), default=0) or 1
    return {
        "days": days,
        "rows": [{"letter": k, "label": label, "seen": seen.get(k, 0),
                  "kept": kept.get(k, 0),
                  "seen_pct": round(100 * seen.get(k, 0) / top),
                  "kept_pct": round(100 * kept.get(k, 0) / top)}
                 for k, label in FAMILIES.items()],
    }
