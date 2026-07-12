"""Lecture de la veille quotidienne du pipeline Claude cowork.

Le pipeline écrit chaque matin `Veille quotidienne/<YYYY-MM-DD>/Compte
rendu.md` dans JOB_SEARCH_DIR. On en extrait les offres retenues (titre,
détail, liens de candidature) et la conclusion, sans toucher aux fichiers.
"""
import re
from datetime import date, datetime
from pathlib import Path

from flask import current_app

_RETAINED_RE = re.compile(
    r"^##\s*Offres retenues[^\n]*$(.*?)(?=^##\s|\Z)", re.M | re.S)
_CONCLUSION_RE = re.compile(
    r"^##\s*Conclusion\s*$(.*?)(?=^##\s|\Z)", re.M | re.S)
_LINK_RE = re.compile(r"https?://[^\s)>\]]+")


def _parse_offers(section_text):
    offers = []
    for block in re.split(r"^###\s+", section_text, flags=re.M)[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        title = re.sub(r"^\d+\.\s*", "", lines[0]).strip()
        body = "\n".join(lines[1:]).strip()
        offers.append({
            "title": title,
            "body": body,
            "links": _LINK_RE.findall(body),
        })
    return offers


def parse_report(text, day, dirname):
    retained = _RETAINED_RE.search(text)
    conclusion = _CONCLUSION_RE.search(text)
    return {
        "date": day,
        "dirname": dirname,
        "is_today": day == date.today() if day else False,
        "offers": _parse_offers(retained.group(1)) if retained else [],
        "conclusion": conclusion.group(1).strip() if conclusion else "",
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


def get_daily_reports(limit=14):
    """Comptes rendus des derniers jours, du plus récent au plus ancien.

    Renvoie None si JOB_SEARCH_DIR n'est pas configuré ou introuvable.
    """
    root = current_app.config.get("JOB_SEARCH_DIR") or ""
    base = Path(root) / "Veille quotidienne"
    if not root or not base.is_dir():
        return None

    reports = []
    for d in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
        if not d.is_dir():
            continue
        f = d / "Compte rendu.md"
        if not f.is_file():
            continue
        try:
            day = datetime.strptime(d.name, "%Y-%m-%d").date()
        except ValueError:
            day = None
        try:
            text = f.read_text(encoding="utf-8")
        except OSError:
            continue
        reports.append(parse_report(text, day, d.name))
        if len(reports) >= limit:
            break
    return reports
