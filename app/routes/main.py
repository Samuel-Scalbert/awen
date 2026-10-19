from datetime import date

from flask import Blueprint, render_template

from ..models import Workout
from ..services import charges, charts, coach, todos
from ..services.job_watch import date_fr, freshness, get_daily_reports
from ..services.progression import (REPRISE, TRAINING_WEEKDAYS, rotation,
                                    upcoming)
from ..services.stats import overview
from .workout import _current_workout, exercises_for

bp = Blueprint("main", __name__)

# Au-delà, la colonne devient une liste à lire : l'accueil montre de quoi
# reconnaître la séance, la page Séance montre le reste.
APERCU = 5


def _cible(pe):
    """« 4 × 8-12 à 80 lb » : ce qu'il faut faire, en une ligne."""
    if pe.rep_min and pe.rep_max and pe.rep_min != pe.rep_max:
        reps = f"{pe.rep_min}-{pe.rep_max}"
    else:
        reps = str(pe.rep_max or pe.rep_min or "")
    cible = f"{pe.sets} × {reps}" + (" s" if pe.unit == "sec" else "")
    if pe.weight_kg and pe.block != "plyo":
        cible += " à " + charges.label(pe.weight_kg, pe)
    return cible


def _apercu(focus):
    # La reprise contient tout le programme : la lister ici ferait un mur.
    exercices = [] if focus == REPRISE else exercises_for(focus)
    return {
        "exercices": [{"nom": pe.name, "cible": _cible(pe)}
                      for pe in exercices[:APERCU]],
        "reste": max(0, len(exercices) - APERCU),
        "prevues": sum(pe.sets or 0 for pe in exercices),
        "ids": {pe.id for pe in exercices},
    }


def _seance(today):
    """La séance du jour, telle que l'accueil la résume.

    Quatre états, parce qu'ils appellent quatre gestes : en cours (reprendre),
    jour d'entraînement (choisir), faite (rien à faire), repos (savoir quand
    vient la suivante). La séance proposée n'est qu'une suggestion, celle qui
    attend depuis le plus longtemps : le choix se fait à la salle. Lire la
    page ne crée jamais de séance.
    """
    current = _current_workout()
    # Une séance ouverte un autre jour et jamais remplie ne sera pas
    # reprise : elle disparaît au prochain choix, l'accueil l'ignore déjà.
    if current is not None and not current.sets and current.date.date() != today:
        current = None
    if current is not None:
        a = _apercu(current.focus)
        faites = (sum(1 for s in current.sets if s.program_exercise_id in a["ids"])
                  if a["ids"] else len(current.sets))
        jour = current.date.date()
        return dict(a, etat="en_cours", focus=current.focus, faites=faites,
                    depuis=jour if jour != today else None)

    recentes = (Workout.query.filter_by(completed=True)
                .order_by(Workout.date.desc()).limit(5))
    # Une séance fermée sans une seule série n'est pas une séance faite.
    faite = next((w for w in recentes
                  if w.date.date() == today and w.sets), None)
    if faite is not None:
        return {"etat": "faite", "focus": faite.focus, "faites": len(faite.sets)}

    suggestion = rotation()[0]
    if today.weekday() in TRAINING_WEEKDAYS:
        return dict(_apercu(suggestion), etat="prevue", focus=suggestion)
    jour, focus = upcoming(today, count=1)[0]
    # « mercredi 14 octobre », sans l'année : on parle de cette semaine.
    return {"etat": "repos", "focus": focus,
            "prochaine": date_fr(jour).rsplit(" ", 1)[0].lower()}


def _veille():
    """Le dernier compte rendu de veille emploi, réduit à ce qui se décide."""
    reports = get_daily_reports(limit=1)
    if not reports:
        return None
    r = reports[0]
    verdicts = [o["verdict"]["kind"] for o in r["offers"] if o["verdict"]]
    return {
        "rapport": r,
        "n": len(r["offers"]),
        "go": verdicts.count("go"),
        "premiere": r["offers"][0] if r["offers"] else None,
        "missions": len(r["missions"]),
        "alerte": freshness(reports),
    }


@bp.route("/")
def index():
    """Accueil : ce qu'il y a à faire aujourd'hui, puis la progression.

    La journée passe avant les totaux : en ouvrant l'app on veut savoir quoi
    faire, pas combien on a soulevé depuis juillet.
    """
    today = date.today()
    o = overview()
    volume_chart = charts.line_chart(
        [(s["date"].strftime("%d/%m"), s["volume"]) for s in o["sessions"]],
        fmt=lambda v: f"{v / 1000:.1f} t".replace(".", ",") if v >= 1000 else f"{v:g} kg")
    compte = todos.counts()
    return render_template(
        "index.html", o=o, volume_chart=volume_chart,
        headline=coach.headline(), recap=coach.weekly_recap(),
        jour=date_fr(today).rsplit(" ", 1)[0], today=today,
        seance=_seance(today), veille=_veille(),
        taches=todos.pending(4), compte=compte)
