"""Le poste de commande : HUD plein écran, chat, pavé numérique, voix."""
import shutil
import subprocess

from flask import (Blueprint, Response, current_app, jsonify, render_template,
                   request)

from ..services import jarvis as svc
from ..services import todos

bp = Blueprint("jarvis", __name__, url_prefix="/jarvis")

# Les touches du pavé numérique. Le libellé est ce qu'affiche la touche
# dessinée dans le HUD, la phrase est ce qui part vraiment. Un libellé tient
# sur une touche : neuf lettres au plus.
#
# Les codes sont ceux du navigateur (`event.code`) : `Numpad7` est distinct
# de `Digit7`, donc la touche du pavé ne se confond pas avec celle du haut du
# clavier. Ce que le navigateur ne sait PAS, c'est de quel clavier physique
# vient la frappe — d'où la règle appliquée dans jarvis.js : un raccourci ne
# part que si le champ de saisie n'a pas le focus.
PAVE = [
    ("Numpad7", "Séance", "Je fais quoi aujourd'hui ?"),
    ("Numpad8", "Progrès", "Montre-moi ma progression"),
    ("Numpad9", "Coach", "Quel est le conseil du coach ?"),
    ("Numpad4", "Macros", "Mes macros du jour"),
    ("Numpad5", "Ce soir", "Qu'est-ce que je mange ce soir ?"),
    ("Numpad6", "Courses", "Ma liste de courses"),
    ("Numpad1", "Agenda", "Mes prochains rendez-vous"),
    ("Numpad2", "Tâches", "Mes tâches en cours"),
    ("Numpad3", "Emploi", "La veille emploi du jour"),
    ("Numpad0", "Suivante", "Quelle est ma prochaine tâche ?"),
    ("NumpadDecimal", "Faite", "Marque ma prochaine tâche comme terminée"),
    ("NumpadAdd", "Répète", None),        # traité côté navigateur
    ("NumpadSubtract", "Stop", None),     # idem : couper la lecture
    ("NumpadEnter", "Détaille", "Développe ta réponse précédente"),
    ("NumpadMultiply", "Serveur", "Comment va le serveur ?"),
    ("NumpadDivide", "Libre", None),      # idem : ouvre la saisie libre
]

# La disposition physique d'un pavé numérique, rangée par rangée. Le HUD la
# redessine telle quelle, pour que l'œil retrouve à l'écran la touche que le
# doigt connaît déjà. « haute » et « large » sont les touches doubles ; la
# grille CSS place les autres autour d'elles.
DISPOSITION = [
    ("NumLock", "Verr", ""), ("NumpadDivide", "/", ""),
    ("NumpadMultiply", "*", ""), ("NumpadSubtract", "-", ""),
    ("Numpad7", "7", ""), ("Numpad8", "8", ""), ("Numpad9", "9", ""),
    ("NumpadAdd", "+", "haute"),
    ("Numpad4", "4", ""), ("Numpad5", "5", ""), ("Numpad6", "6", ""),
    ("Numpad1", "1", ""), ("Numpad2", "2", ""), ("Numpad3", "3", ""),
    ("NumpadEnter", "↵", "haute"),
    ("Numpad0", "0", "large"), ("NumpadDecimal", ".", ""),
]


def _clavier():
    """Les touches dans l'ordre de la grille, avec leur rôle."""
    roles = {code: (libelle, phrase) for code, libelle, phrase in PAVE}
    return [{"code": code, "legende": legende, "forme": forme,
             "libelle": roles.get(code, ("", None))[0],
             "phrase": roles.get(code, ("", None))[1]}
            for code, legende, forme in DISPOSITION]


@bp.route("/")
def hud():
    return render_template("jarvis.html", pave=PAVE, clavier=_clavier())


@bp.route("/taches/<int:todo_id>/terminer", methods=["POST"])
def terminer_tache(todo_id):
    """Cocher une tâche depuis le HUD, sans passer par le modèle.

    Sur le processeur, demander à Jarvis de la cocher prend une dizaine de
    secondes. Un clic doit être instantané. La liste à jour repart dans la
    réponse, pour que le HUD n'attende pas son prochain relevé.
    """
    if todos.complete(todo_id) is None:
        return jsonify({"ok": False}), 404
    return jsonify({"ok": True, "taches": svc.etat_complet()["taches"]})


@bp.route("/etat")
def etat():
    """Interrogé toutes les cinq secondes par la barre haute."""
    return jsonify(svc.etat_complet())


@bp.route("/demander", methods=["POST"])
def demander():
    data = request.get_json(silent=True) or {}
    reponse = svc.ask(data.get("question"), data.get("historique"))
    # Quand le modèle n'est pas joignable, on interroge quand même les outils
    # et on renvoie la donnée brute : mieux vaut un tableau que rien du tout.
    if not reponse["ok"]:
        repli = svc.sans_modele(data.get("question"))
        if repli["ok"]:
            reponse["repli"] = repli
    return jsonify(reponse)


@bp.route("/voix")
def voix():
    """Synthèse vocale par Piper, si Piper est installé.

    Renvoie 503 quand il ne l'est pas — et ce n'est pas une panne : le
    navigateur bascule alors sur sa propre synthèse vocale, qui parle français
    sans rien installer. C'est ce qui permet à Jarvis d'avoir une voix dès
    aujourd'hui, avant même le pilote NVIDIA.
    """
    texte = (request.args.get("texte") or "").strip()[:800]
    modele = current_app.config["PIPER_MODEL"]
    if not texte:
        return jsonify({"erreur": "rien à dire"}), 400
    if not shutil.which("piper") or not modele:
        return jsonify({"erreur": "piper absent",
                        "repli": "navigateur"}), 503
    try:
        out = subprocess.run(
            ["piper", "--model", modele, "--output_file", "-"],
            input=texte.encode("utf-8"), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=30, check=True)
    except (subprocess.SubprocessError, OSError) as exc:
        return jsonify({"erreur": type(exc).__name__,
                        "repli": "navigateur"}), 503
    return Response(out.stdout, mimetype="audio/wav")
