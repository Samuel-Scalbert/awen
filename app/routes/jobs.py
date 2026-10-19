import re
from datetime import datetime
from io import BytesIO

import markdown as md
from flask import (Blueprint, abort, jsonify, redirect,
                   render_template, request, send_file, send_from_directory,
                   url_for)

from ..models import CoverLetter, LetterLesson, db
from ..services import lettres as lettres_svc
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
    for m in report["missions"]:
        m["why_html"] = _render_md(m["sections"].get("why", ""))
        m["caveat_html"] = _render_md(m["sections"].get("caveat", ""))
        facts = [("Engagement", m["commitment"]), ("Places", m["places"])]
        facts += [(f["label"], f["value"]) for f in m["other_fields"]]
        m["facts"] = [(label, _render_inline(cap(v))) for label, v in facts if v]
        for x in m["other_sections"]:
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
    ecrites = CoverLetter.query.order_by(CoverLetter.id.desc()).limit(30).all()
    for lettre in ecrites:
        lettres_svc.abandonnee(lettre)
    return render_template(
        "lettres.html", letters=get_cover_letters(), ecrites=ecrites,
        offres=lettres_svc.offres_recentes(),
        lecons=LetterLesson.query.order_by(LetterLesson.id.desc()).all(),
        moteur=lettres_svc.moteur(),
        choisie=request.args.get("offre", ""))


# --------------------------------------------------------------------------
# Écrire une lettre avec Claude


def _champs(lettre):
    """Ce que la page sait de la lettre, pour l'éditeur et le suivi."""
    return {
        "id": lettre.id, "etat": lettre.etat, "erreur": lettre.erreur,
        "entreprise": lettre.entreprise, "poste": lettre.poste,
        "expediteur": lettre.expediteur, "date_ligne": lettre.date_ligne,
        "destinataire": lettre.destinataire, "objet": lettre.objet,
        "salutation": lettre.salutation, "corps": lettre.corps,
        "notes": lettre.notes, "mots": lettres_svc.mots(lettre),
    }


def _nouvelle(offre, offre_ref, priorites, entreprise="", poste=""):
    lettre = CoverLetter(
        offre=offre, offre_ref=offre_ref, priorites=priorites,
        entreprise=entreprise, poste=poste, etat="generation",
        expediteur=lettres_svc.expediteur_par_defaut(),
        date_ligne=lettres_svc.date_du_jour())
    db.session.add(lettre)
    db.session.commit()
    lettres_svc.lancer(lettres_svc.generer, lettre.id)
    return lettre


@bp.route("/lettres/nouvelle", methods=["POST"])
def letter_new():
    """Une offre de la veille ou un texte collé, et ce qu'il faut mettre en avant."""
    ref = request.form.get("offre_ref", "").strip()
    texte = request.form.get("offre", "").strip()
    priorites = request.form.get("priorites", "").strip()
    entreprise = poste = ""
    if ref:
        o = next((o for o in lettres_svc.offres_recentes() if o["ref"] == ref),
                 None)
        if o is not None:
            # Un texte collé en plus de l'offre choisie la complète.
            texte = (o["texte"] + ("\n\n" + texte if texte else "")).strip()
            entreprise, poste = o["entreprise"], o["poste"]
    if not texte:
        return redirect(url_for("jobs.letters"))
    lettre = _nouvelle(texte, ref, priorites, entreprise, poste)
    return redirect(url_for("jobs.letter_edit", lettre_id=lettre.id))


@bp.route("/lettres/<int:lettre_id>")
def letter_edit(lettre_id):
    lettre = db.session.get(CoverLetter, lettre_id) or abort(404)
    lettres_svc.abandonnee(lettre)
    return render_template(
        "lettre_edition.html", lettre=lettre, champs=_champs(lettre),
        lecons=LetterLesson.query.filter_by(active=True).count())


@bp.route("/lettres/<int:lettre_id>/etat")
def letter_state(lettre_id):
    lettre = db.session.get(CoverLetter, lettre_id) or abort(404)
    lettres_svc.abandonnee(lettre)
    return jsonify(_champs(lettre))


def _maj(lettre, data):
    for cle in ("expediteur", "date_ligne", "destinataire", "objet",
                "salutation", "corps", "entreprise"):
        if cle in data:
            setattr(lettre, cle, (data.get(cle) or "").replace("\r\n", "\n"))


@bp.route("/lettres/<int:lettre_id>/enregistrer", methods=["POST"])
def letter_save(lettre_id):
    lettre = db.session.get(CoverLetter, lettre_id) or abort(404)
    _maj(lettre, request.get_json(silent=True) or request.form)
    db.session.commit()
    return jsonify(ok=True, mots=lettres_svc.mots(lettre))


@bp.route("/lettres/<int:lettre_id>/regenerer", methods=["POST"])
def letter_regenerate(lettre_id):
    """Une nouvelle lettre pour la même offre : l'ancienne reste dans
    l'historique, avec ses corrections, plutôt que d'être écrasée."""
    ancienne = db.session.get(CoverLetter, lettre_id) or abort(404)
    priorites = request.form.get("priorites", ancienne.priorites).strip()
    lettre = _nouvelle(ancienne.offre, ancienne.offre_ref, priorites,
                       ancienne.entreprise, ancienne.poste)
    return redirect(url_for("jobs.letter_edit", lettre_id=lettre.id))


@bp.route("/lettres/<int:lettre_id>/pdf", methods=["POST"])
def letter_pdf(lettre_id):
    """Enregistre la version corrigée, renvoie le PDF, et apprend de l'écart."""
    lettre = db.session.get(CoverLetter, lettre_id) or abort(404)
    _maj(lettre, request.form)
    try:
        contenu = lettres_svc.pdf(lettre)
    except lettres_svc.LettreErreur as e:
        db.session.commit()
        return jsonify(ok=False, erreur=str(e)), 422
    lettre.exportee_le = datetime.now()
    db.session.commit()
    if lettres_svc.a_etudier(lettre):
        lettres_svc.lancer(lettres_svc.etudier, lettre.id)
    return send_file(BytesIO(contenu), mimetype="application/pdf",
                     as_attachment=True,
                     download_name=lettres_svc.nom_fichier(lettre))


@bp.route("/lettres/<int:lettre_id>/md")
def letter_markdown(lettre_id):
    """La lettre en .md, pour la ranger dans le projet Recherche de CDI."""
    lettre = db.session.get(CoverLetter, lettre_id) or abort(404)
    return send_file(BytesIO(lettres_svc.markdown(lettre).encode("utf-8")),
                     mimetype="text/markdown", as_attachment=True,
                     download_name=lettres_svc.nom_markdown(lettre))


@bp.route("/lettres/<int:lettre_id>/supprimer", methods=["POST"])
def letter_delete(lettre_id):
    lettre = db.session.get(CoverLetter, lettre_id) or abort(404)
    # Ses leçons restent : elles valent pour les lettres suivantes, pas
    # pour celle-ci. Elles perdent seulement leur lien.
    LetterLesson.query.filter_by(lettre_id=lettre.id).update({"lettre_id": None})
    db.session.delete(lettre)
    db.session.commit()
    return redirect(url_for("jobs.letters"))


@bp.route("/lettres/lecons/<int:lecon_id>", methods=["POST"])
def lesson_toggle(lecon_id):
    """Active, désactive ou supprime une leçon."""
    lecon = db.session.get(LetterLesson, lecon_id) or abort(404)
    action = request.form.get("action")
    if action == "supprimer":
        db.session.delete(lecon)
    else:
        lecon.active = not lecon.active
    db.session.commit()
    return redirect(url_for("jobs.letters") + "#lecons")


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
