"""Le coach : observe l'historique et propose des ajustements.

Principe de conception : **toutes les décisions chiffrées sont déterministes**.
Chaque conseil vient d'une règle explicite et testable, accompagnée de la raison
qui l'a déclenchée. Rien n'est modifié dans le dos de l'utilisateur : l'analyse
propose, il applique — et toute application est journalisée dans CoachDecision,
pour rester relisible et contestable.

Gravité des observations :
  alert  — quelque chose cloche, il faut agir
  warn   — à surveiller
  info   — observation utile
  good   — ça marche, on le dit aussi
"""
from collections import defaultdict
from datetime import date, timedelta

from ..models import (BodyWeight, CoachDecision, ExerciseSet, JumpTest,
                      ProgramExercise, Workout, db)
from .progression import TRAINING_WEEKDAYS, working_sets

# Seuils regroupés ici pour être discutables d'un coup d'œil, plutôt que
# disséminés au fil des règles.
RANGE_MIN_RATIO = 50   # % de séries dans la fourchette sous lequel la charge est jugée inadaptée
STALL_SESSIONS = 3     # séances à charge identique avant de parler de stagnation
DELOAD_RATIO = 0.9     # -10 % pour casser un plateau
EASY_RIR = 3           # RIR >= 3 : trop de réserve, c'est trop léger
JUMP_TEST_DAYS = 28    # au-delà, le test de détente est à refaire
WEIGH_IN_DAYS = 10     # au-delà, la pesée est trop ancienne pour juger
IDLE_DAYS = 4          # au-delà, on relance sur l'assiduité


def _sessions_of(pe, completed):
    """Historique d'un exercice, séance par séance."""
    sets = [s for s in ExerciseSet.query.filter_by(program_exercise_id=pe.id)
            .order_by(ExerciseSet.id) if s.workout_id in completed]
    by_workout = defaultdict(list)
    for s in sets:
        by_workout[s.workout_id].append(s)

    out = []
    for wid in sorted(by_workout, key=lambda i: completed[i]):
        ws = working_sets(by_workout[wid], pe.sets)
        weights = sorted((x.weight_kg or 0) for x in ws)
        rirs = [x.rir for x in ws if x.rir is not None]
        out.append({
            "date": completed[wid],
            "weight": weights[len(weights) // 2] if weights else 0,
            "reps": [x.reps or 0 for x in ws],
            "rir": min(rirs) if rirs else None,   # la série la plus dure
            "sets": by_workout[wid],
        })
    return out


def _adherence_advice(completed, today, advice):
    if not completed:
        return
    last = max(completed.values())
    idle = (today - last).days
    days = sorted(completed.values())
    long_gap = max((days[i] - days[i - 1]).days
                   for i in range(1, len(days))) if len(days) > 1 else 0

    if idle >= IDLE_DAYS:
        advice.append({
            "level": "alert", "icon": "📉",
            "title": f"{idle} jours sans séance",
            "detail": "Le programme le mieux réglé ne rattrape pas les séances "
                      "manquées. Reprends même léger : une séance à 70 % vaut "
                      "infiniment mieux qu'une séance sautée.",
        })
    if long_gap >= 14:
        advice.append({
            "level": "warn", "icon": "📅",
            "title": f"Ton plus long arrêt : {long_gap} jours",
            "detail": "C'est ce qui coûte le plus cher à ta progression, bien "
                      "plus que le choix des exercices ou la taille des paliers.",
        })


def _bodyweight_advice(today, advice):
    weights = BodyWeight.query.order_by(BodyWeight.date).all()
    if not weights:
        advice.append({
            "level": "warn", "icon": "⚖️", "title": "Aucune pesée enregistrée",
            "detail": "Sans ton poids, impossible de dire si une stagnation vient "
                      "du programme ou de l'alimentation. Une pesée par semaine "
                      "suffit, le matin à jeun.",
            "action": "weight",
        })
        return

    last = weights[-1]
    if (today - last.date).days > WEIGH_IN_DAYS:
        advice.append({
            "level": "warn", "icon": "⚖️",
            "title": f"Dernière pesée il y a {(today - last.date).days} jours",
            "detail": "Repèse-toi pour que le coach puisse relier tes charges à "
                      "ta prise de masse.",
            "action": "weight",
        })

    recent = [w for w in weights if (today - w.date).days <= 21]
    if len(recent) < 2:
        return
    delta = recent[-1].weight_kg - recent[0].weight_kg
    span = max((recent[-1].date - recent[0].date).days, 1)
    per_month = delta * 30 / span
    if per_month < 0.2:
        advice.append({
            "level": "alert", "icon": "🍚",
            "title": f"Poids quasi stable ({delta:+.1f} kg en {span} j)",
            "detail": "En prise de masse, on vise +0,5 à 1 kg/mois. Si tes charges "
                      "stagnent aussi, le problème est dans l'assiette et pas dans "
                      "le programme : ajoute 200 kcal par jour.",
        })
    elif per_month > 1.5:
        advice.append({
            "level": "warn", "icon": "🍚",
            "title": f"Prise rapide ({per_month:+.1f} kg/mois projeté)",
            "detail": "Au-delà d'environ 1 kg/mois, la part de gras augmente. "
                      "Retire 200 kcal si ça se confirme la semaine prochaine.",
        })
    else:
        advice.append({
            "level": "good", "icon": "🍚",
            "title": f"Prise de masse dans la cible ({per_month:+.1f} kg/mois)",
            "detail": "Continue exactement comme ça.",
        })


def _jump_advice(today, advice):
    jumps = JumpTest.query.order_by(JumpTest.date).all()
    if not jumps:
        advice.append({
            "level": "warn", "icon": "🏐", "title": "Détente jamais mesurée",
            "detail": "Tu fais de la pliométrie pour sauter plus haut, mais rien "
                      "ne le vérifie. Un test au mur donnera le point de départ.",
            "action": "jump",
        })
        return
    age = (today - jumps[-1].date).days
    if age >= JUMP_TEST_DAYS:
        advice.append({
            "level": "info", "icon": "🏐",
            "title": f"Test de détente vieux de {age} jours",
            "detail": f"Dernière mesure : {jumps[-1].height_cm:g} cm. Refais-en "
                      "un pour voir si la plyométrie paie.",
            "action": "jump",
        })
    elif len(jumps) >= 2:
        gain = jumps[-1].height_cm - jumps[0].height_cm
        advice.append({
            "level": "good" if gain > 0 else "info", "icon": "🏐",
            "title": f"Détente : {jumps[-1].height_cm:g} cm ({gain:+.1f} cm)",
            "detail": "Depuis ton premier test.",
        })


def _harder(pe):
    """Charge rendant l'exercice plus difficile.

    On garde le SIGNE de increment_kg : sur les tractions assistées il est
    négatif, car durcir l'exercice veut dire retirer de l'assistance. Prendre
    la valeur absolue inverserait la consigne sur ces exercices-là.
    """
    return round(max(0, pe.weight_kg + pe.increment_kg), 1)


def _easier(pe):
    return round(max(0, pe.weight_kg - pe.increment_kg), 1)


def _deload(pe):
    """-10 % de difficulté (donc +10 % d'assistance si l'exercice est assisté)."""
    ratio = DELOAD_RATIO if pe.increment_kg > 0 else (2 - DELOAD_RATIO)
    return round(pe.weight_kg * ratio, 1)


def _exercise_advice(pe, hist, advice):
    """Une seule consigne par exercice : la plus urgente."""
    recent = hist[-STALL_SESSIONS:]
    all_sets = [s for h in recent for s in h["sets"]]
    in_range = sum(1 for s in all_sets
                   if s.reps and pe.rep_min <= s.reps <= pe.rep_max)
    ratio = 100 * in_range // len(all_sets) if all_sets else 100

    # Règle 1 — la fourchette n'est pas tenue : la charge est mal réglée
    if ratio < RANGE_MIN_RATIO and pe.increment_kg:
        reps = [r for h in recent for r in h["reps"]]
        if sum(1 for r in reps if r > pe.rep_max) >= sum(1 for r in reps if r < pe.rep_min):
            new = _harder(pe)
            why = (f"{ratio} % des séries seulement dans la cible "
                   f"{pe.rep_min}-{pe.rep_max} : tu dépasses le haut de la "
                   f"fourchette, la charge est trop légère.")
        else:
            new = _easier(pe)
            why = (f"{ratio} % des séries seulement dans la cible "
                   f"{pe.rep_min}-{pe.rep_max} : tu n'atteins pas le bas de la "
                   f"fourchette, la charge est trop lourde.")
        advice.append({
            "level": "alert", "icon": "🎯",
            "title": f"{pe.name} — {'assistance' if pe.increment_kg < 0 else 'charge'} "
                     f"inadaptée",
            "detail": why, "exercise": pe, "action": "set_weight",
            "new_weight": new,
        })
        return

    # Règle 2 — trop de réserve : on monte sans attendre la fin du cycle
    last_rir = hist[-1]["rir"]
    if last_rir is not None and last_rir >= EASY_RIR and pe.increment_kg:
        new = _harder(pe)
        advice.append({
            "level": "warn", "icon": "🚀",
            "title": f"{pe.name} — trop facile",
            "detail": f"Il te restait {last_rir} reps en réserve à la dernière "
                      f"séance : la charge ne stimule plus. Passe à {new:g} kg.",
            "exercise": pe, "action": "set_weight", "new_weight": new,
        })
        return

    # Règle 3 — stagnation : même charge depuis plusieurs séances
    if len(hist) >= STALL_SESSIONS and pe.increment_kg:
        if len({h["weight"] for h in hist[-STALL_SESSIONS:]}) == 1:
            new = _deload(pe)
            advice.append({
                "level": "warn", "icon": "🔁",
                "title": f"{pe.name} — stagne depuis {STALL_SESSIONS} séances",
                "detail": f"Même charge ({pe.weight_kg:g} kg) sans progresser. Un "
                          f"deload à {new:g} kg (-10 %) casse le plateau : tu "
                          f"remonteras plus vite qu'en t'acharnant.",
                "exercise": pe, "action": "set_weight", "new_weight": new,
            })
            return

    # Règle 4 — poids du corps : aucune charge à ajouter
    if not pe.increment_kg or not pe.weight_kg:
        if len(hist) >= 2 and sum(hist[-1]["reps"]) <= sum(hist[-2]["reps"]):
            advice.append({
                "level": "info", "icon": "➕",
                "title": f"{pe.name} — progresser autrement",
                "detail": "Pas de charge à ajouter ici : la progression passe par "
                          "les répétitions, puis par une série supplémentaire "
                          f"(tu es à {pe.sets}).",
                "exercise": pe,
            })


def analyse():
    """Toutes les observations du moment, les plus graves d'abord."""
    today = date.today()
    completed = {w.id: w.date.date()
                 for w in Workout.query.filter_by(completed=True)}
    advice = []

    _adherence_advice(completed, today, advice)
    _bodyweight_advice(today, advice)
    _jump_advice(today, advice)

    for pe in (ProgramExercise.query.filter(ProgramExercise.active.is_(True))
               .order_by(ProgramExercise.session_type, ProgramExercise.position)):
        if pe.block == "plyo":
            continue
        hist = _sessions_of(pe, completed)
        if hist:
            _exercise_advice(pe, hist, advice)

    order = {"alert": 0, "warn": 1, "info": 2, "good": 3}
    advice.sort(key=lambda a: order[a["level"]])
    return advice


def apply_advice(pe_id, new_weight, reason):
    """Applique un conseil et le journalise."""
    pe = db.session.get(ProgramExercise, pe_id)
    if pe is None:
        return None
    old = pe.weight_kg
    pe.weight_kg = new_weight
    db.session.add(CoachDecision(
        program_exercise_id=pe.id, kind="conseil coach",
        reason=(reason or "")[:300], old_weight=old, new_weight=new_weight))
    db.session.commit()
    return pe


def headline(advice=None):
    """La phrase la plus importante du moment — pour l'accueil et l'ESP32."""
    advice = analyse() if advice is None else advice
    return advice[0] if advice else None


def weekly_recap():
    """Résumé de la semaine en cours, pour l'accueil et l'ESP32."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sessions = [w for w in Workout.query.filter_by(completed=True)
                if w.date.date() >= monday]
    planned = sum(1 for i in range(today.weekday() + 1)
                  if (monday + timedelta(days=i)).weekday() in TRAINING_WEEKDAYS)
    volume = sum((s.reps or 0) * (s.weight_kg or 0)
                 for w in sessions for s in w.sets)
    decisions = (CoachDecision.query
                 .filter(CoachDecision.created_at >= monday)
                 .order_by(CoachDecision.created_at.desc()).all())
    return {
        "sessions": len(sessions), "planned": planned,
        "volume": round(volume), "decisions": decisions,
        "on_track": len(sessions) >= planned,
    }
