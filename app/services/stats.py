"""Agrégations statistiques sur l'historique d'entraînement.

Conventions (les mêmes partout, pour que les chiffres soient comparables) :

- **Volume** = Σ (reps × charge) en kg. C'est la mesure de travail la plus
  parlante en prise de masse. Les exercices au poids du corps (charge 0) ne
  produisent aucun volume : les reps sont donc suivies séparément pour qu'ils
  ne deviennent pas invisibles.
- **e1RM** (max théorique à 1 rep) via la formule d'Epley : `w × (1 + reps/30)`.
  Fiable jusqu'à ~12 reps, ce qui couvre les fourchettes du programme ; c'est
  le meilleur indicateur de force réelle quand la charge ET les reps bougent.
- Seules les séances **terminées** comptent dans les statistiques : une séance
  en cours est incomplète par nature et fausserait les moyennes.
"""
from collections import defaultdict
from datetime import date, timedelta

from ..models import ExerciseSet, ProgramExercise, Workout
from .progression import CYCLE, TRAINING_WEEKDAYS, working_sets

# Slots validés pour un fond sombre (voir la validation de palette dataviz) :
# toujours accompagnés d'un libellé, jamais la couleur seule.
FOCUS_COLORS = {"Push": "#3987e5", "Pull": "#d95926", "Legs": "#199e70"}


def e1rm(weight, reps):
    """Max théorique à 1 rep (Epley). None si la charge n'est pas pertinente."""
    if not weight or not reps:
        return None
    return round(weight * (1 + reps / 30), 1)


def set_volume(s):
    return (s.reps or 0) * (s.weight_kg or 0)


def _completed_workouts():
    return (Workout.query.filter_by(completed=True)
            .order_by(Workout.date, Workout.id).all())


def overview():
    """Chiffres clés + séries temporelles pour la page de statistiques."""
    workouts = _completed_workouts()
    today = date.today()

    sessions = []
    for w in workouts:
        vol = sum(set_volume(s) for s in w.sets)
        reps = sum(s.reps or 0 for s in w.sets)
        sessions.append({
            "id": w.id,
            "date": w.date.date(),
            "focus": w.focus,
            "sets": len(w.sets),
            "reps": reps,
            "volume": round(vol),
            "notes": w.notes or "",
        })

    total_volume = sum(s["volume"] for s in sessions)
    total_sets = sum(s["sets"] for s in sessions)
    total_reps = sum(s["reps"] for s in sessions)

    # Assiduité : séances faites vs jours d'entraînement écoulés depuis la 1re
    planned = 0
    if sessions:
        d = sessions[0]["date"]
        while d <= today:
            if d.weekday() in TRAINING_WEEKDAYS:
                planned += 1
            d += timedelta(days=1)
    adherence = round(100 * len(sessions) / planned) if planned else 0

    # Rythme réel : séances par semaine sur la période couverte
    per_week = 0.0
    if len(sessions) >= 2:
        span_days = (sessions[-1]["date"] - sessions[0]["date"]).days + 1
        per_week = round(len(sessions) * 7 / max(span_days, 1), 1)

    # Écart moyen / maximal entre deux séances : révèle les trous
    gaps = [(sessions[i]["date"] - sessions[i - 1]["date"]).days
            for i in range(1, len(sessions))]
    avg_gap = round(sum(gaps) / len(gaps), 1) if gaps else 0
    max_gap = max(gaps) if gaps else 0
    days_since = (today - sessions[-1]["date"]).days if sessions else None

    # Répartition par type de séance et volume associé
    by_focus = {f: {"sessions": 0, "volume": 0, "sets": 0} for f in CYCLE}
    for s in sessions:
        if s["focus"] in by_focus:
            by_focus[s["focus"]]["sessions"] += 1
            by_focus[s["focus"]]["volume"] += s["volume"]
            by_focus[s["focus"]]["sets"] += s["sets"]

    # Fréquence par jour de semaine : est-ce que le planning lun/mer/ven
    # est tenu, ou est-ce que les séances glissent ?
    weekdays = [0] * 7
    for s in sessions:
        weekdays[s["date"].weekday()] += 1

    # Volume par semaine ISO (tendance de charge de travail)
    weekly = defaultdict(int)
    for s in sessions:
        monday = s["date"] - timedelta(days=s["date"].weekday())
        weekly[monday] += s["volume"]
    weekly_series = [{"week": k, "volume": v} for k, v in sorted(weekly.items())]

    return {
        "sessions": sessions,
        "n_sessions": len(sessions),
        "total_volume": total_volume,
        "total_sets": total_sets,
        "total_reps": total_reps,
        "avg_volume": round(total_volume / len(sessions)) if sessions else 0,
        "planned": planned,
        "adherence": adherence,
        "per_week": per_week,
        "avg_gap": avg_gap,
        "max_gap": max_gap,
        "days_since": days_since,
        "by_focus": by_focus,
        "weekdays": weekdays,
        "weekly": weekly_series,
        "first_date": sessions[0]["date"] if sessions else None,
        "last_date": sessions[-1]["date"] if sessions else None,
    }


def exercise_rows():
    """Une ligne de synthèse par exercice du programme, la plus travaillée d'abord."""
    completed_ids = {w.id for w in Workout.query.filter_by(completed=True)}
    rows = []
    for pe in ProgramExercise.query.order_by(ProgramExercise.session_type,
                                             ProgramExercise.position).all():
        sets = [s for s in ExerciseSet.query
                .filter_by(program_exercise_id=pe.id).order_by(ExerciseSet.id)
                if s.workout_id in completed_ids]
        if not sets:
            rows.append({"pe": pe, "n_sets": 0, "sessions": 0, "volume": 0,
                         "first_weight": None, "best_weight": None,
                         "best_e1rm": None, "in_range": None, "trend": []})
            continue

        by_workout = defaultdict(list)
        for s in sets:
            by_workout[s.workout_id].append(s)

        # Charge de travail retenue par séance : la médiane des séries de
        # travail, insensible à une série d'essai ou d'échauffement isolée.
        trend = []
        for wid in sorted(by_workout):
            ws = working_sets(by_workout[wid], pe.sets)
            weights = sorted((s.weight_kg or 0) for s in ws)
            if weights:
                trend.append(weights[len(weights) // 2])

        best = max(sets, key=lambda s: (s.weight_kg or 0, s.reps or 0))
        e1 = [(e1rm(s.weight_kg, s.reps), s) for s in sets]
        e1 = [(v, s) for v, s in e1 if v is not None]
        best_e1 = max(e1, key=lambda t: t[0]) if e1 else None
        in_range = sum(1 for s in sets
                       if s.reps and pe.rep_min <= s.reps <= pe.rep_max)

        rows.append({
            "pe": pe,
            "n_sets": len(sets),
            "sessions": len(by_workout),
            "volume": round(sum(set_volume(s) for s in sets)),
            "first_weight": trend[0] if trend else None,
            "best_weight": best.weight_kg,
            "best_reps": best.reps,
            "best_e1rm": best_e1[0] if best_e1 else None,
            "in_range": round(100 * in_range / len(sets)),
            "trend": trend,
        })
    rows.sort(key=lambda r: r["volume"], reverse=True)
    return rows


def exercise_detail(pe):
    """Historique séance par séance d'un exercice, pour sa page dédiée."""
    completed = {w.id: w for w in Workout.query.filter_by(completed=True)}
    sets = [s for s in ExerciseSet.query
            .filter_by(program_exercise_id=pe.id).order_by(ExerciseSet.id)
            if s.workout_id in completed]

    by_workout = defaultdict(list)
    for s in sets:
        by_workout[s.workout_id].append(s)

    history = []
    for wid in sorted(by_workout, key=lambda i: completed[i].date):
        ws = sorted(by_workout[wid], key=lambda s: s.id)
        work = working_sets(ws, pe.sets)
        weights = sorted((s.weight_kg or 0) for s in work)
        best = max((e1rm(s.weight_kg, s.reps) or 0) for s in ws)
        history.append({
            "workout_id": wid,
            "date": completed[wid].date.date(),
            "sets": ws,
            "n_sets": len(ws),
            "weight": weights[len(weights) // 2] if weights else 0,
            "volume": round(sum(set_volume(s) for s in ws)),
            "reps_total": sum(s.reps or 0 for s in ws),
            "best_e1rm": round(best, 1) if best else None,
            "in_range": all(s.reps and pe.rep_min <= s.reps <= pe.rep_max
                            for s in work) if work else False,
        })
    return history
