"""La dictée, depuis l'écran d'accueil du téléphone.

La page s'installe comme une application (Chrome, menu, « Ajouter à l'écran
d'accueil ») grâce à son manifeste. Le micro du navigateur ne s'ouvre que
sur une adresse HTTPS : c'est celle de Tailscale,
https://awen.tailc9ff94.ts.net, qui sert Awen au téléphone partout, pas
seulement à la maison.
"""
import json
from datetime import date, datetime

from flask import Blueprint, current_app, jsonify, render_template, request, url_for

from ..services import agenda_google
from ..services import dictee as svc

bp = Blueprint("dictee", __name__, url_prefix="/dictee")


def _dt(raw):
    try:
        return datetime.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        return None


def _d(raw):
    try:
        return date.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        return None


@bp.route("/")
def page():
    return render_template("dictee.html", agenda=agenda_google.actif())


@bp.route("/manifest.webmanifest")
def manifest():
    icone = lambda taille, but: {
        "src": url_for("static", filename="img/dictee-{}.png".format(taille)),
        "sizes": "{0}x{0}".format(taille), "type": "image/png", "purpose": but}
    data = {
        "id": url_for("dictee.page"),
        "name": "Awen Dictée",
        "short_name": "Dictée",
        "description": "Dis une chose à faire : elle va dans l'agenda Awen.",
        "lang": "fr",
        "start_url": url_for("dictee.page", auto=1),
        "scope": url_for("dictee.page"),
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#0f1115",
        "theme_color": "#0f1115",
        "icons": [icone(192, "any"), icone(512, "any"), icone(512, "maskable")],
    }
    return current_app.response_class(json.dumps(data, ensure_ascii=False),
                                      mimetype="application/manifest+json")


@bp.route("/analyser", methods=["POST"])
def analyser():
    texte = ((request.get_json(silent=True) or {}).get("texte") or "").strip()
    if not texte:
        return jsonify({"erreur": "Je n'ai rien entendu."}), 400
    r = svc.analyser(texte)
    return jsonify({
        "phrase": r["phrase"],
        "titre": r["titre"],
        "quand": r["debut"].strftime("%Y-%m-%dT%H:%M") if r["debut"] else "",
        "jour": r["jour"].isoformat() if r["jour"] else "",
        "libelle": svc.libelle(r["debut"], r["jour"]),
    })


@bp.route("/libelle")
def libelle():
    """Le libellé, recalculé quand on corrige la date sur l'aperçu."""
    return jsonify({"libelle": svc.libelle(_dt(request.args.get("quand")),
                                           _d(request.args.get("jour")))})


@bp.route("/ajouter", methods=["POST"])
def ajouter():
    d = request.get_json(silent=True) or {}
    if not (d.get("titre") or "").strip():
        return jsonify({"erreur": "Le titre est vide."}), 400
    debut = _dt(d.get("quand"))
    jour = None if debut else _d(d.get("jour"))
    return jsonify(svc.ajouter(d["titre"], debut, jour))


@bp.route("/annuler", methods=["POST"])
def annuler():
    d = request.get_json(silent=True) or {}
    try:
        svc.annuler(d.get("type"), d.get("id"))
    except Exception as exc:                         # Google injoignable...
        current_app.logger.warning("dictée, annulation : %s", exc)
        return jsonify({"erreur": "Pas pu annuler : retire-le dans l'agenda."}), 502
    return jsonify({"ok": True})
