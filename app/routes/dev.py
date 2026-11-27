"""API des récaps de fin de session Claude Code.

Le PC pousse un récap par projet quand une session se termine ; PhoneBox le
relit. Authentifié par `DEV_API_KEY`, une clé à part : on peut la révoquer
sans rien casser ailleurs.

Le serveur n'est pas exposé sur Internet (pas de port ouvert sur la box), la
clé protège donc surtout d'une écriture accidentelle depuis le LAN.
"""
import hmac

from flask import Blueprint, Response, abort, current_app, jsonify, request

from ..services.dev_recap import board_text, load_recaps, save_recap

bp = Blueprint("dev", __name__, url_prefix="/api/dev")


def _check_key():
    # En query string aussi : le widget Command de PhoneBox lance une
    # commande, pas forcément un client qui sait poser un en-tête.
    attendue = current_app.config.get("DEV_API_KEY") or ""
    # Sans clé configurée, la route est fermée : une valeur par défaut
    # connue de tous (« change-me ») ouvrirait l'écriture à tout le réseau.
    if not attendue or attendue == "change-me":
        abort(503, description="DEV_API_KEY n'est pas définie dans le .env du serveur.")
    key = request.headers.get("X-API-Key") or request.args.get("key")
    if not key or not hmac.compare_digest(key, attendue):
        abort(401)


@bp.route("/recap", methods=["POST"])
def post_recap():
    _check_key()
    recap = save_recap(request.get_json(silent=True))
    if recap is None:
        # 422 et pas 400 : le JSON est lisible, c'est son contenu qui ne
        # convient pas. Le script PowerShell distingue les deux pour savoir
        # s'il doit réessayer.
        abort(422, description="Charge utile invalide (champ 'project' manquant ou illisible).")
    return jsonify(recap), 201


@bp.route("/recaps")
def get_recaps():
    _check_key()
    return jsonify(load_recaps())


@bp.route("/board")
def get_board():
    _check_key()
    # text/plain : la sortie part telle quelle dans le widget Command.
    return Response(board_text(), mimetype="text/plain; charset=utf-8")
