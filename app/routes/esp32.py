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
import unicodedata
from datetime import date, datetime, timedelta
from hashlib import sha1

from flask import (Blueprint, Response, abort, current_app, jsonify, request)

from ..models import ProgramExercise, Workout, db
from ..services.coach import analyse, apply_advice
from ..services.job_watch import get_daily_reports
from ..services import calendar_sync
from ..services import host as host_svc
from ..services import saints
from ..services import todos as todos_svc
from ..services import spotify as spotify_svc
from ..services import weather as weather_svc
from ..services import charges
from ..services.progression import (CYCLE, TRAINING_WEEKDAYS, rotation,
                                    upcoming)

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
        if pe.unit == "sec":
            detail = "{} x {}s".format(pe.sets, pe.rep_max or 0)
        elif pe.weight_kg:
            # Sur les crans de la machine (« 36.3 kg x 12 ») ; la police de
            # l'écran n'a pas de virgule.
            charge = charges.label(pe.weight_kg, pe).replace(",", ".")
            detail = "{} x {}".format(charge, pe.rep_max or 0)
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


def _spotify_block(clean=_ascii):
    """L'état de lecture, tronqué aux 28 colonnes utiles de l'écran.

    `clean` nettoie les textes : sans accents pour la police 8x8 des sept
    écrans, avec pour les polices des trois pages.
    """
    sp = spotify_svc.now_playing()
    # now_playing() renvoie None si Spotify n'est pas configuré, mais aussi
    # un {"device": ""} nu quand rien ne joue ou que l'API a échoué. Ne
    # tester que None faisait lever un KeyError sur sp["title"] dès que la
    # lecture s'arrêtait, et c'est tout /summary qui retournait alors une
    # erreur 500 — l'afficheur restait figé sur ses dernières données.
    if not sp or not sp.get("device"):
        return {"device": ""}          # l'écran sait dire « aucun appareil »
    # Un identifiant court de pochette plutôt que l'URL : l'ESP32 s'en sert
    # uniquement pour savoir si l'image a changé, et une URL Spotify fait
    # 64 caractères qu'il transporterait toutes les cinq secondes pour rien.
    #
    # Une empreinte de l'URL entière, pas un morceau du nom de fichier : les
    # URL Spotify commencent toutes par le même préfixe (ab67616d00004851
    # désigne la taille, pas l'album), donc découper le début donnait un
    # identifiant identique pour toutes les pochettes — et une image qui ne
    # se rafraîchissait jamais.
    art = sp.get("art_url") or ""
    return {
        "title": clean(sp["title"])[:56],
        "artist": clean(sp["artist"])[:28],
        "album": clean(sp["album"])[:28],
        "position_s": sp["position_s"],
        "duration_s": sp["duration_s"],
        "volume": sp["volume"],
        "playing": sp["playing"],
        "device": clean(sp["device"])[:12],
        "cover": sha1(art.encode()).hexdigest()[:12] if art else "",
    }


@bp.route("/cover")
def spotify_cover():
    """La pochette en cours, en pixels bruts pour blit_buffer().

    Servie en octets plutôt qu'en JPEG : l'ESP32 ne sait pas décoder une
    image, et le redimensionnement se fait ici où il coûte quelques
    millisecondes au lieu de plusieurs secondes là-bas.
    """
    _check_key()
    # Sans paramètre : l'ancien afficheur, 112 px en blocs. Avec ?size= : le
    # firmware à trois pages, qui choisit sa taille et la veut lisse.
    size = request.args.get("size", type=int)
    if size is None:
        size, block = spotify_svc.COVER_SIZE, spotify_svc.COVER_BLOCK
    else:
        size = max(spotify_svc.COVER_MIN, min(spotify_svc.COVER_MAX, size))
        block = 1
    sp = spotify_svc.now_playing()
    data = spotify_svc.cover_rgb565((sp or {}).get("art_url", ""), size, block)
    if data is None:
        abort(404)
    return Response(data, mimetype="application/octet-stream",
                    headers={"X-Cover-Size": str(size)})


JOURS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi",
         "Dimanche")
MOIS = ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
        "aout", "septembre", "octobre", "novembre", "decembre")


def _day_block(today):
    """Date en toutes lettres et saint du jour, déjà mis en forme."""
    return {
        "long": "{} {} {}".format(JOURS[today.weekday()], today.day,
                                  MOIS[today.month - 1]),
        "saint": saints.of(today),
        "semaine": today.isocalendar()[1],
    }


def _weather_block():
    w = weather_svc.today()
    if w is None:
        return {"ok": False}
    return {
        "ok": True,
        "now_c": w["now_c"],
        "min_c": w["min_c"],
        "max_c": w["max_c"],
        "rain_pct": w["rain_pct"],
        "label": _ascii(w["label"])[:20],
        "icon": w["icon"],
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

    # Suggestions, plus planning : la séance se choisit à la salle, et la
    # première proposée est celle qui attend depuis le plus longtemps.
    fait = any(w.sets for w in workouts if w.date.date() == today)
    after = today if fait else today - timedelta(days=1)
    planned = upcoming(after, count=8)
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
            "next_focus": next_focus or rotation()[0],
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
        "jour": _day_block(today),
        "meteo": _weather_block(),
        # Deja tronquees a 30 colonnes et prefixees : la carte
        # interprete du MicroPython, tout ce qu'on prepare ici est
        # autant de travail qu'elle n'a pas a faire.
        "taches": {"n": todos_svc.counts()["pending"],
                   "lignes": [_ascii(l) for l in todos_svc.lines(3, COLS)]},
        "serveur": host_svc.summary(),
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


# --------------------------------------------------------------------------
# Les trois pages : Accueil, Spotify, Calendrier
#
# Le firmware à trois pages lit /pages et non /summary. Il n'a plus besoin de
# la séance, du coach, des offres ni du serveur, et un JSON deux fois plus
# court se lit deux fois plus vite sur une carte qui compte ses octets.
# /summary reste en place tant qu'un afficheur à sept écrans peut encore
# l'appeler.

AGENDA_JOURS = 14       # jusqu'où le calendrier regarde
AGENDA_LIGNES = 14      # évènements envoyés à la page Calendrier, au plus
AGENDA_ACCUEIL = 4      # lignes de l'accueil
TITRE_MAX = 30          # l'écran coupe au pixel ; ceci borne seulement le JSON

MOIS_ACCENTS = ("janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre",
                "décembre")
JOURS_CAPS = ("LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI", "SAMEDI",
              "DIMANCHE")
JOURS_3 = ("LUN", "MAR", "MER", "JEU", "VEN", "SAM", "DIM")
LETTRES = "LMMJVSD"

# Les caractères que les polices de l'afficheur savent tracer : l'ASCII et
# les accents du français. Voir scripts/gen_fonts.py, qui doit lister les
# mêmes.
_ACCENTS = set("àâäçéèêëîïôöùûüÿœÀÂÇÉÈÊËÎÏÔÙÛÜŒ°")
_SIGNES = {"’": "'", "‘": "'", "“": '"', "”": '"', "«": '"', "»": '"',
           "–": "-", "—": "-", "·": "-", "…": "...", " ": " ",
           " ": " ", "æ": "ae", "Æ": "AE"}

# Sous la colonne PLUIE il reste dix caractères : le libellé complet de la
# météo (« BRUINE VERGLACANTE ») n'y tient pas. Pour une pluie, l'en-tête dit
# déjà « pluie », il ne reste qu'à dire laquelle.
_CIEL_COURT = {
    "PEU NUAGEUX": "ECLAIRCIES", "NUAGES EPARS": "NUAGEUX",
    "BROUILLARD GIVRANT": "BROUILLARD", "BRUINE FORTE": "BRUINE",
    "BRUINE VERGLACANTE": "VERGLAS", "PLUIE FAIBLE": "FAIBLE",
    "PLUIE": "MODEREE", "PLUIE FORTE": "FORTE",
    "PLUIE VERGLACANTE": "VERGLAS", "NEIGE FAIBLE": "NEIGE",
    "NEIGE FORTE": "NEIGE", "GRAINS DE NEIGE": "NEIGE",
    "AVERSES FORTES": "AVERSES", "AVERSES DE NEIGE": "NEIGE",
    "ORAGE ET GRELE": "GRELE",
}


def _latin(s):
    """Garde ce que l'afficheur sait écrire, accents compris.

    Un caractère hors jeu est ramené à sa lettre de base quand il en a une
    (« ñ » devient « n »), sinon remplacé par une espace : un emoji dans un
    titre d'agenda ne doit ni planter la carte ni laisser un carré vide.
    """
    out = []
    for ch in s or "":
        if 32 <= ord(ch) < 127 or ch in _ACCENTS:
            out.append(ch)
        elif ch in _SIGNES:
            out.append(_SIGNES[ch])
        else:
            base = unicodedata.normalize("NFKD", ch)[:1]
            out.append(base if base and 32 < ord(base) < 127 else " ")
    return " ".join("".join(out).split())


def _dans(minutes):
    """« DANS 45 MIN », « DANS 1 H 19 » : le temps avant le prochain."""
    if minutes < 60:
        return "DANS {} MIN".format(max(1, minutes))
    h, m = divmod(minutes, 60)
    return "DANS {} H {:02d}".format(h, m) if m else "DANS {} H".format(h)


def _ligne(e, etat):
    heure = "" if e["all_day"] else e["start"].strftime("%H:%M")
    return [heure, _latin(e["title"])[:TITRE_MAX], etat]


def _agenda_block(now):
    """L'agenda, déjà trié et étiqueté pour les deux pages qui le montrent.

    Chaque ligne vaut [heure, titre, état]. L'heure est vide pour une
    journée entière. L'état : 0 passé, 1 celui qu'on met en avant (en cours,
    ou le prochain), 2 à venir.

    L'accueil reçoit quatre lignes d'aujourd'hui au plus, cadrées sur ce qui
    arrive : à dix-huit heures, les rendez-vous du matin n'ont plus à
    occuper l'écran. Le calendrier reçoit ce qui reste d'aujourd'hui puis
    les jours suivants.
    """
    today = now.date()
    lundi = today - timedelta(days=today.weekday())
    events, status = calendar_sync.occurrences(
        lundi, today + timedelta(days=AGENDA_JOURS - 1))

    par_jour = {}
    for e in events:
        par_jour.setdefault(e["start"].date(), []).append(e)

    # --- aujourd'hui ------------------------------------------------------
    du_jour, vedette, dans = [], None, ""
    for e in par_jour.get(today, []):
        if e["all_day"]:
            etat = 2
        elif max(e["end"], e["start"] + timedelta(minutes=1)) <= now:
            etat = 0
        elif vedette is None:
            etat, vedette = 1, len(du_jour)
            attente = (e["start"] - now).total_seconds()
            dans = "EN COURS" if attente <= 0 else _dans(int(-(-attente // 60)))
        else:
            etat = 2
        du_jour.append(_ligne(e, etat))

    debut = 0
    if len(du_jour) > AGENDA_ACCUEIL:
        repere = len(du_jour) if vedette is None else vedette
        debut = max(0, min(repere - 1, len(du_jour) - AGENDA_ACCUEIL))

    # --- les jours qui viennent -------------------------------------------
    jours, reste = [], AGENDA_LIGNES
    for k in range(AGENDA_JOURS):
        d = today + timedelta(days=k)
        if k == 0:
            lignes = [l for l in du_jour if l[2] != 0]
        else:
            lignes = [_ligne(e, 2) for e in par_jour.get(d, [])]
        lignes = lignes[:reste]
        if not lignes:
            continue
        reste -= len(lignes)
        titre = ("AUJOURD'HUI", "DEMAIN")[k] if k < 2 else JOURS_CAPS[d.weekday()]
        jours.append({"t": titre,
                      "d": "{} {}".format(JOURS_3[d.weekday()], d.day),
                      "ev": lignes})
        if reste <= 0:
            break

    semaine = []
    for i in range(7):
        d = lundi + timedelta(days=i)
        semaine.append([LETTRES[i], d.day, 1 if par_jour.get(d) else 0])

    return {
        "ok": status == "ok",
        "n": len(du_jour),
        "jour": du_jour[debut:debut + AGENDA_ACCUEIL],
        "dans": dans,
        "jours": jours,
        "semaine": semaine,
        "auj": today.weekday(),
        "mois": MOIS_ACCENTS[today.month - 1].capitalize(),
        "annee": today.year,
    }


def _weather_pages():
    m = _weather_block()
    if m.get("ok"):
        label = m.pop("label", "")
        m.pop("icon", None)
        m["court"] = _CIEL_COURT.get(label, label)[:10]
    return m


@bp.route("/pages")
def pages():
    """Tout ce que montrent les trois pages, en un seul appel."""
    _check_key()
    now = datetime.now()
    today = now.date()
    return jsonify({
        "ok": True,
        # L'heure en minutes depuis minuit, et les secondes : la carte n'a
        # pas d'horloge sauvegardée, mais elle sait compter. Avec ces deux
        # nombres elle fait avancer la minute elle-même, au lieu d'afficher
        # jusqu'à trente secondes de retard entre deux appels.
        "min": now.hour * 60 + now.minute,
        "sec": now.second,
        "jour": {
            "long": "{} {} {}".format(JOURS[today.weekday()], today.day,
                                      MOIS_ACCENTS[today.month - 1]),
            "semaine": today.isocalendar()[1],
        },
        "meteo": _weather_pages(),
        "agenda": _agenda_block(now),
        "spotify": _spotify_block(_latin),
    })
