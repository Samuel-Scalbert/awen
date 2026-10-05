import re

import markdown as md
from flask import (Blueprint, abort, render_template, request,
                   send_from_directory)

from ..services.job_watch import (FAMILIES, cap, family_totals, freshness,
                                  get_cover_letters, get_daily_reports,
                                  get_report, letters_dir, read_cover_letter)

bp = Blueprint("jobs", __name__, url_prefix="/jobs")


def _render_md(text):
    # Les comptes rendus recopient des annonces du web : on neutralise toute
    # balise HTML avant le Markdown, pour qu'une annonce piégée ne puisse pas
    # glisser de script dans Awen. Les liens « <https://...> » restent permis.
    safe = re.sub(r"<(?!https?://)", "&lt;", text or "")
    # Espaces insécables de la typographie française : sinon un « » » ou un
    # « ? » se retrouve seul en tête de ligne sur un écran étroit.
    safe = re.sub(r"« ", "« ", safe)
    safe = re.sub(r" ([»:;!?])", " \\1", safe)
    return md.markdown(safe, extensions=["tables"])


def _render_inline(text):
    """Markdown d'une seule ligne, sans le paragraphe qui l'entoure."""
    html = _render_md(text).strip()
    if html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
        return html[3:-4]
    return html


def _age(offer):
    n = offer["age_days"]
    if n is None:
        return "", ""
    n = max(n, 0)
    label = ("publiée aujourd'hui" if n == 0 else "publiée hier" if n == 1
             else f"publiée il y a {n} j")
    # Les bonnes offres partent en moins de 48 heures ; au-delà de sept
    # jours, la tâche ne peut plus dire « Postuler aujourd'hui ».
    return label, "fresh" if n <= 1 else "old" if n >= 7 else ""


def _prepare(report):
    """Rend en HTML tout ce que le gabarit affiche d'un compte rendu."""
    for o in report["offers"]:
        s = o["sections"]
        for kind in ("fit", "research", "angle", "question"):
            o[kind + "_html"] = _render_md(s.get(kind, ""))
        o["age_label"], o["age_kind"] = _age(o)
        facts = [("Salaire", o["salary"]), ("Expérience", o["experience"]),
                 ("Lieu", o["location"]), ("CV", o["cv"])]
        facts += [(f["label"], f["value"]) for f in o["other_fields"]]
        o["facts"] = [(label, _render_inline(cap(v))) for label, v in facts if v]
        o["links_note_html"] = _render_md(o["links_note"])
        for x in o["other_sections"]:
            x["html"] = _render_md(x["text"])
    for x in report["extras"]:
        x["html"] = _render_md(x["text"])
    report["sources_html"] = _render_inline(report["sources"])
    report["alerts_html"] = [_render_inline(a) for a in report["alerts"]]
    report["notes_html"] = _render_md(report["notes"])
    report["rejected_html"] = _render_md(report["rejected"])
    report["conclusion_html"] = _render_md(report["conclusion"])
    report["raw_html"] = _render_md(report["raw"])
    kinds = [o["verdict"]["kind"] for o in report["offers"] if o["verdict"]]
    report["n_go"], report["n_maybe"] = kinds.count("go"), kinds.count("maybe")
    split = report["split"]
    report["split_rows"] = [
        {"letter": k, "label": label, "seen": split["seen"].get(k, 0),
         "kept": split["kept"].get(k, 0)}
        for k, label in FAMILIES.items()] if split else []


@bp.route("/lettres")
def letters():
    return render_template("lettres.html", letters=get_cover_letters())


@bp.route("/lettres/lire/<path:filename>")
def read_letter(filename):
    text = read_cover_letter(filename)
    if text is None:
        abort(404)
    return render_template("lettre.html", filename=filename,
                           title=filename.rsplit(".", 1)[0],
                           content_html=_render_md(text))


@bp.route("/lettres/telecharger/<path:filename>")
def download_letter(filename):
    base = letters_dir()
    if base is None:
        abort(404)
    return send_from_directory(base, filename, as_attachment=True)


@bp.route("/")
def daily_jobs():
    reports = get_daily_reports(limit=14)
    sel = banner = families = None
    if reports:
        wanted = request.args.get("jour", "")
        sel = next((r for r in reports if r["dirname"] == wanted), None)
        if sel is None and wanted:
            sel = get_report(wanted)
        sel = sel or reports[0]
        _prepare(sel)
        banner = freshness(reports)
        families = family_totals(reports)
    return render_template("jobs.html", reports=reports, sel=sel,
                           banner=banner, families=families)
