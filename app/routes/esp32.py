"""API légère consommée par l'ESP32 pour l'affichage sur écran.

Payload volontairement compact et pré-formaté (chaînes prêtes à dessiner) :
l'ESP32 tourne en MicroPython interprété, tout ce qu'on calcule ici est
autant de travail qu'il n'a pas à faire. L'écran fait 30 colonnes, donc les
chaînes sont déjà tronquées à la bonne longueur.

Ce que l'afficheur ne fait PAS : enregistrer des séries. Il est posé sur un
bureau, pas dans la salle — le téléphone est en main là-bas. La séance y est
donc en lecture seule, un aperçu de ce qui attend. Seul le coach a des
boutons, parce que trancher un conseil depuis son bureau, ça, c'est naturel.
"""
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, current_app, jsonify, request

from ..models import ProgramExercise, Workout, db
from ..services.coach import analyse, apply_advice
from ..services.job_watch import get_daily_reports
from ..services import spotify as spotify_svc
from ..services.progression import (CYCLE, TRAINING_WEEKDAYS,
                                    next_session_type, plan_upcoming)

bp = Blueprint("esp32", __name__, url_prefix="/api/esp32")

DAYS_FR = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]

COLS = 30          # largeur de l'écran, en caractères
TITLE_MAX = 38     # la phrase du coach, déjà tronquée pour la barre haute

# Le web affiche des emoji ; la police 8x8 de l'ESP32 n'en a aucun et les
# rendrait en carrés vides. On envoie un marqueur ASCII à la place, que
# l'afficheur peut colorer selon le niveau.
MARKERS = {"alert": "!", "warn": "*", "info": "-", "good": "+"}


def _check_key():
    key = request.headers.get("X-API-Key") or request.args.get("key")
    if key != current_app.config["ESP32_API_KEY"]:
        abort(401)


def _short_date(d):
    return "{} {:02d}/{:02d}".format(DAYS_FR[d.weekday()], d.day, d.month)


def _ascii(s):
    """Retire les accents : la police 8x8 de l'afficheur ne les a pas.

    Sans ça, « SÉANCE » sort en « S?ANCE » sur la carte. On le fait ici
    plutôt que sur l'ESP32 : c'est du travail en moins pour lui, et la
    table de correspondance vit à un seul endroit.
    """
    out = []
    for ch in s or "":
        out.append({
            "à": "a", "â": "a", "ä": "a", "ç": "c", "é": "e", "è": "e",
            "ê": "e", "ë": "e", "î": "i", "ï": "i", "ô": "o", "ö": "o",
            "ù": "u", "û": "u", "ü": "u", "ÿ": "y", "œ": "oe", "æ": "ae",
            "·": "-", "–": "-", "—": "-", "’": "'", "«": '"', "»": '"',
        }.get(ch, ch if 32 <= ord(ch) < 127 else " "))
    return "".join(out)


def _wrap(text, width, lines):
    """Découpe aux espaces, en un nombre fixe de lignes déjà rembourrées."""
    words, out, cur = _ascii(text).split(), [], ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            out.append(cur)
            cur = w
            if len(out) == lines:
                break
    if cur and len(out) < lines:
        out.append(cur)
    return (out + [""] * lines)[:lines]


def _session_preview(focus, last_workout):
    """Les exercices programmés d'une séance, prêts à afficher.

    On lit les charges dans le programme, pas dans l'historique : c'est
    exactement ce que le coach a décidé pour la prochaine fois, donc ce que
    l'afficheur doit annoncer.
    """
    if not focus:
        return []
    rows = (ProgramExercise.query
            .filter(ProgramExercise.session_type == focus.lower(),
                    ProgramExercise.active.is_(True),
                    ProgramExercise.block != "plyo")
            .order_by(ProgramExercise.position))
    out = []
    for pe in rows:
        if pe.unit == "duree":
            detail = "{} x {}s".format(pe.sets, pe.rep_max or 0)
        elif pe.weight_kg:
            detail = "{:g} kg x {}".format(pe.weight_kg, pe.rep_max or 0)
        else:
            detail = "{} x {}".format(pe.sets, pe.rep_max or 0)
        # Le nom et la charge partagent une ligne de 30 colonnes : le nom
        # commence en colonne 2, la charge est calée à droite. Tronquer le
        # nom à une longueur fixe le ferait donc percuter les charges longues
        # (« TRACTIONS (ASSIST. » contre « 40 kg x 10 »). On lui donne ce qui
        # reste, moins une colonne de respiration.
        budget = COLS - 2 - len(detail) - 1
        out.append({
            "name": _ascii(pe.name)[:budget],
            "detail": detail,
            "sets": pe.sets,
        })
    return out


def _coach_block():
    """Le conseil prioritaire, déjà découpé aux dimensions de l'écran."""
    advice = analyse()
    if not advice:
        return {"level": "", "icon": "", "text": "", "subject": "",
                "detail": ["", ""], "from_kg": None, "to_kg": None,
                "pe_id": None}
    top = advice[0]
    pe = top.get("exercise")
    return {
        "level": top["level"],
        "icon": MARKERS.get(top["level"], "-"),
        "text": _ascii(top["title"])[:TITLE_MAX],
        "subject": _ascii(pe.name) if pe is not None else "",
        "detail": _wrap(top.get("detail", ""), COLS - 2, 2),
        "from_kg": pe.weight_kg if pe is not None else None,
        "to_kg": top.get("new_weight"),
        "pe_id": pe.id if pe is not None else None,
    }


def _spotify_block():
    """L'état de lecture, tronqué aux 28 colonnes utiles de l'écran."""
    sp = spotify_svc.now_playing()
    if sp is None:
        return {"device": ""}          # non configuré : l'écran le dira
    return {
        "title": _ascii(sp["title"])[:56],
        "artist": _ascii(sp["artist"])[:28],
        "album": _ascii(sp["album"])[:28],
        "position_s": sp["position_s"],
        "duration_s": sp["duration_s"],
        "volume": sp["volume"],
        "playing": sp["playing"],
        "device": _ascii(sp["device"])[:12],
    }


@bp.route("/summary")
def summary():
    _check_key()
    today = date.today()
    now = datetime.now()

    workouts = Workout.query.order_by(Workout.date, Workout.id).all()
    last_focus, last_date, last_workout = None, None, None
    for w in reversed(workouts):
        if w.focus in CYCLE:
            last_focus, last_date, last_workout = w.focus, w.date.date(), w
            break

    after = max(filter(None, [last_date, today - timedelta(days=1)]))
    planned = plan_upcoming(last_focus, after, count=8)
    planned_today = next((f for d, f in planned if d == today), None)
    next_day, next_focus = planned[0] if planned else (None, None)

    today_workouts = [w for w in workouts if w.date.date() == today]
    done_today = any(w.completed for w in today_workouts)
    in_progress = any(not w.completed for w in today_workouts)

    # Séances ratées : jours d'entraînement passés depuis la dernière séance
    missed = 0
    if last_date:
        d = last_date + timedelta(days=1)
        while d < today:
            if d.weekday() in TRAINING_WEEKDAYS:
                missed += 1
            d += timedelta(days=1)
        missed = min(missed, 9)

    preview_focus = planned_today or next_focus
    exercises = _session_preview(preview_focus, last_workout)

    reports = get_daily_reports(limit=1) or []
    jobs_today, offers = 0, []
    if reports and reports[0]["date"] == today:
        found = reports[0]["offers"]
        jobs_today = len(found)
        # Pas de champ « organisme » : le pipeline ne le sépare pas du titre,
        # et le deviner en coupant à la première virgule marcherait un jour
        # sur deux. On envoie le titre, l'écran le replie sur trois lignes.
        offers = [{"title": _wrap(o["title"], COLS - 2, 3)} for o in found[:6]]

    return jsonify({
        "ok": True,
        "time": now.strftime("%H:%M"),
        "date": _short_date(today),
        "gym": {
            "today": planned_today or "",          # "" = repos aujourd'hui
            "done": done_today,
            "live": in_progress,
            "missed": missed,
            "next": "{} {}".format(_short_date(next_day), next_focus)
                    if next_day else "",
            "next_focus": next_focus or next_session_type(last_focus),
            "last": "{} {}".format(last_focus, _short_date(last_date))
                    if last_date else "",
            "session_no": len([w for w in workouts if w.focus in CYCLE]),
            "focus": preview_focus or "",
            "exercises": exercises,
        },
        "jobs": {
            "n": jobs_today,
            "offers": offers,
        },
        "coach": _coach_block(),
        "spotify": _spotify_block(),
    })


@bp.route("/spotify", methods=["POST"])
def spotify_action():
    """Télécommande : play, pause, toggle, next, previous, volume."""
    _check_key()
    body = request.get_json(silent=True) or {}
    ok, detail = spotify_svc.command(body.get("action", ""), body.get("value"))
    return jsonify(ok=ok, detail=detail), (200 if ok else 502)


@bp.route("/advice", methods=["POST"])
def advice_action():
    """Applique ou ignore le conseil prioritaire, depuis les boutons.

    On relit le conseil au lieu de faire confiance au corps de la requête :
    l'afficheur n'envoie qu'une intention, jamais une charge. Une charge qui
    voyagerait sur le réseau pourrait arriver périmée, et c'est exactement le
    genre de chiffre qu'on ne veut pas laisser décider ailleurs que dans le
    moteur de règles.
    """
    _check_key()
    body = request.get_json(silent=True) or {}
    if not body.get("accept"):
        return jsonify(ok=True, applied=False)

    advice = analyse()
    if not advice:
        return jsonify(ok=True, applied=False, reason="rien a appliquer")

    top = advice[0]
    pe = top.get("exercise")
    if pe is None or top.get("new_weight") is None:
        return jsonify(ok=True, applied=False, reason="conseil non chiffre")

    updated = apply_advice(pe.id, top["new_weight"], "applique depuis l'ESP32")
    if updated is None:
        abort(404)
    return jsonify(ok=True, applied=True, exercise=updated.name,
                   weight_kg=updated.weight_kg)
