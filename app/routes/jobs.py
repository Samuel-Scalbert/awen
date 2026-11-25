import re
from datetime import datetime
from io import BytesIO

import markdown as md
from flask import (Blueprint, abort, flash, jsonify, redirect,
                   render_template, request, send_file, send_from_directory,
                   url_for)

from ..models import (CollecteLevees, CoverLetter, LetterLesson, Levee,
                      MailProspection, OffreRattrapee, db)
from ..models.levee import STATUTS
from ..services import lettres as lettres_svc
from ..services import levees as levees_svc
from ..services import rattrapage
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
    # Chaque offre écartée, une par une, pour pouvoir la rattraper.
    deja = {(o.entreprise, o.intitule) for o in
            OffreRattrapee.query.filter_by(rapport=report["dirname"])}
    blocs = rattrapage.blocs_ecartees(report["rejected"])
    for b in blocs:
        if b["kind"] == "md":
            b["html"] = _render_md(b["text"])
        for item in b.get("offres", []):
            item["html"] = _render_inline(item["ligne"])
            item["rattrapee"] = (item["entreprise"], item["intitule"]) in deja
    report["rejected_blocks"] = blocs
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
    choisie = request.args.get("offre", "")
    # Les lettres pas encore exportées passent avant le formulaire : on
    # revient sur cette page pour reprendre une lettre bien plus souvent que
    # pour en commencer une, et sur un téléphone la liste tombait sous un
    # formulaire de trois écrans.
    return render_template(
        "lettres.html", letters=get_cover_letters(),
        en_cours=[l for l in ecrites if not l.exportee_le],
        envoyees=[l for l in ecrites if l.exportee_le],
        deja=next((l for l in ecrites
                   if choisie and l.offre_ref == choisie), None),
        offres=lettres_svc.offres_recentes(),
        lecons=LetterLesson.query.order_by(LetterLesson.id.desc()).all(),
        moteur=lettres_svc.moteur(),
        choisie=choisie)


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


_UNE_LIGNE = ("date_ligne", "objet", "salutation", "entreprise")


def _maj(lettre, data):
    for cle in ("expediteur", "date_ligne", "destinataire", "objet",
                "salutation", "corps", "entreprise"):
        if cle in data:
            v = (data.get(cle) or "").replace("\r\n", "\n")
            # L'objet s'écrit dans une zone qui passe à la ligne, pour se
            # lire en entier sur un téléphone ; il reste une seule ligne
            # dans le PDF.
            if cle in _UNE_LIGNE:
                v = " ".join(x.strip() for x in v.split("\n") if x.strip())
            setattr(lettre, cle, v)


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
    # Une offre qui a déjà sa lettre mène à cette lettre : « Écrire la
    # lettre » rouvrait sinon un formulaire vide, et la lettre commencée
    # depuis le PC semblait perdue quand on revenait depuis le téléphone.
    lettres, rattrapees = {}, []
    if sel:
        for l in (CoverLetter.query
                  .filter(CoverLetter.offre_ref.like(sel["dirname"] + "#%"))
                  .order_by(CoverLetter.id)):
            lettres[l.offre_ref] = l
        rattrapees = (OffreRattrapee.query.filter_by(rapport=sel["dirname"])
                      .order_by(OffreRattrapee.id).all())
        for o in rattrapees:
            o.ref = rattrapage.ref(o)
            o.lettre = (CoverLetter.query.filter_by(offre_ref=o.ref)
                        .order_by(CoverLetter.id.desc()).first())
            o.motif_html = _render_inline(o.motif_ecart)
    return render_template("jobs.html", reports=reports, sel=sel,
                           banner=banner, families=families, lettres=lettres,
                           rattrapees=rattrapees)


@bp.route("/rattraper", methods=["POST"])
def rattraper():
    """Une offre écartée par la veille remonte parmi celles à postuler."""
    rapport = request.form.get("rapport", "")
    ligne = request.form.get("ligne", "").strip()
    if not ligne:
        abort(400)
    o = rattrapage.rattraper(rapport, ligne)
    flash("Offre rattrapée : {}{}.{}".format(
        o.intitule, ", " + o.entreprise if o.entreprise else "",
        "" if o.texte else " L'annonce n'a pas pu être lue : colle-la dans "
        "le formulaire de la lettre."))
    return redirect(url_for("jobs.daily_jobs", jour=rapport) + "#rattrapees")


@bp.route("/rattrapees/<int:offre_id>/annuler", methods=["POST"])
def rattrapage_annuler(offre_id):
    o = db.session.get(OffreRattrapee, offre_id) or abort(404)
    rapport = o.rapport
    rattrapage.annuler(o)
    return redirect(url_for("jobs.daily_jobs", jour=rapport))


# --------------------------------------------------------------------------
# Les levées de fonds et les mails de prospection


def _groupes(levees):
    """Les entreprises par statut, les plus prometteuses en tête de chaque groupe."""
    ordre = (("a_contacter", "À contacter"), ("nouvelle", "Nouvelles"),
             ("contactee", "Contactées"), ("repondu", "Ont répondu"), ("ecartee", "Écartées"))
    par = {k: [] for k, _ in ordre}
    for l in levees:
        par.setdefault(l.statut, []).append(l)
    return [(titre, sorted(par[k], key=lambda l: (-(l.priorite or 0), l.semaine or ""), reverse=False))
            for k, titre in ordre]


@bp.route("/levees")
def levees():
    for m in MailProspection.query.filter_by(etat="generation"):
        levees_svc.abandonne(m)
    collecte = levees_svc.collecte_en_cours() or levees_svc.derniere_collecte()
    toutes = Levee.query.all()
    # Les réglages de la dernière collecte servent aussi de filtre : les
    # grosses levées des collectes d'avant restent en base mais se cachent,
    # sauf celles où une conversation est engagée.
    montant_max = collecte.montant_max if collecte else None
    equipe_max = collecte.equipe_max if collecte else None

    def au_dessus(l):
        if l.statut in ("contactee", "repondu"):
            return False
        e = levees_svc.euros(l.montant)
        return ((montant_max is not None and e is not None and e > montant_max)
                or (equipe_max is not None and l.effectif_max is not None and l.effectif_max > equipe_max))

    tout = request.args.get("tout") == "1"
    masquees = [l for l in toutes if au_dessus(l)]
    visibles = toutes if tout else [l for l in toutes if not au_dessus(l)]
    return render_template("levees.html", collecte=collecte, levees=visibles,
                           groupes=_groupes(visibles), statuts=STATUTS,
                           moteur=lettres_svc.moteur(), masquees=len(masquees), tout=tout,
                           defaut_montant=levees_svc.MONTANT_MAX, defaut_equipe=levees_svc.EQUIPE_MAX)


@bp.route("/levees/collecter", methods=["POST"])
def levees_collect():
    levees_svc.lancer_collecte(request.form.get("semaines", 4),
                               request.form.get("montant_max"), request.form.get("equipe_max"),
                               request.form.getlist("sources"))
    return redirect(url_for("jobs.levees"))


@bp.route("/levees/etat")
def levees_state():
    c = levees_svc.collecte_en_cours() or levees_svc.derniere_collecte()
    if c is None:
        return jsonify(etat="aucune", message="")
    return jsonify(etat=c.etat, message=c.message, nouvelles=c.nb_nouvelles)


@bp.route("/levees/<int:levee_id>/statut", methods=["POST"])
def levee_status(levee_id):
    l = db.session.get(Levee, levee_id) or abort(404)
    statut = request.form.get("statut", "")
    if statut in dict(STATUTS):
        l.statut = statut
        db.session.commit()
    return redirect(url_for("jobs.levees") + "#levee-{}".format(l.id))


@bp.route("/levees/<int:levee_id>/mail", methods=["POST"])
def prospect_mail_new(levee_id):
    l = db.session.get(Levee, levee_id) or abort(404)
    dest = (request.form.get("destinataire_libre", "").strip()
            or request.form.get("destinataire", "").strip())
    m = levees_svc.nouveau_mail(l, dest, request.form.get("consigne", ""))
    return redirect(url_for("jobs.prospect_mail", mail_id=m.id))


def _champs_mail(m):
    return {"id": m.id, "etat": m.etat, "erreur": m.erreur,
            "destinataire": m.destinataire, "objet": m.objet, "corps": m.corps,
            "signature": m.signature, "resume": m.resume, "notes": m.notes,
            "mots": levees_svc.mots(m)}


@bp.route("/levees/mails/<int:mail_id>")
def prospect_mail(mail_id):
    m = db.session.get(MailProspection, mail_id) or abort(404)
    levees_svc.abandonne(m)
    return render_template("mail_prospection.html", mail=m, mots=levees_svc.mots(m))


@bp.route("/levees/mails/<int:mail_id>/etat")
def prospect_mail_state(mail_id):
    m = db.session.get(MailProspection, mail_id) or abort(404)
    levees_svc.abandonne(m)
    return jsonify(_champs_mail(m))


@bp.route("/levees/mails/<int:mail_id>/enregistrer", methods=["POST"])
def prospect_mail_save(mail_id):
    m = db.session.get(MailProspection, mail_id) or abort(404)
    data = request.get_json(silent=True) or request.form
    for cle in ("destinataire", "objet", "corps", "signature"):
        if cle in data:
            v = (data.get(cle) or "").replace("\r\n", "\n")
            if cle in ("destinataire", "objet"):
                v = " ".join(x.strip() for x in v.split("\n") if x.strip())[:200]
            setattr(m, cle, v)
    db.session.commit()
    return jsonify(ok=True, mots=levees_svc.mots(m))


@bp.route("/levees/mails/<int:mail_id>/regenerer", methods=["POST"])
def prospect_mail_regenerate(mail_id):
    """Après une erreur, on relance le même ; sinon une nouvelle version, et
    l'ancienne reste dans la liste avec ses corrections."""
    m = db.session.get(MailProspection, mail_id) or abort(404)
    consigne = request.form.get("consigne", m.consigne)
    if m.etat == "erreur":
        m.etat, m.erreur, m.consigne = "generation", "", consigne
        db.session.commit()
        levees_svc.lancer(levees_svc.generer, m.id)
        return redirect(url_for("jobs.prospect_mail", mail_id=m.id))
    nouveau = levees_svc.nouveau_mail(m.levee, m.destinataire, consigne)
    return redirect(url_for("jobs.prospect_mail", mail_id=nouveau.id))


@bp.route("/levees/mails/<int:mail_id>/envoye", methods=["POST"])
def prospect_mail_sent(mail_id):
    m = db.session.get(MailProspection, mail_id) or abort(404)
    m.envoye_le = datetime.now()
    if m.levee.statut in ("nouvelle", "a_contacter"):
        m.levee.statut = "contactee"
    db.session.commit()
    return redirect(url_for("jobs.prospect_mail", mail_id=m.id))
