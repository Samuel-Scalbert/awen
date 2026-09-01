"""Assiduité : quelles séances ont été manquées, et lesquelles sont excusées.

DEUX FAÇONS DE NE PAS S'ENTRAÎNER

Un été en vacances et trois semaines de canapé produisent le même trou dans
le calendrier, et le coach les traitait pareil. C'est faux, et c'est même
contre-productif : se faire reprocher une absence sur laquelle on n'avait
aucune prise apprend surtout à ignorer le coach.

Un jour manqué est donc :
  absent  — je ne pouvais pas y être. N'entre dans aucun calcul d'assiduité.
  rate    — j'aurais pu, je n'y suis pas allé. Le seul qui compte contre toi.
  None    — pas encore qualifié. Signalé, mais jamais compté : le coach ne
            devine pas à ta place.

RIEN N'EST STOCKÉ SAUF LA QUALIFICATION

La liste des jours manqués se déduit de TRAINING_WEEKDAYS et des séances
faites. Créer une ligne par jour manqué remplirait la base de lignes vides et
obligerait à les tenir à jour à chaque séance enregistrée.
"""
from datetime import date, timedelta

from ..models import MissedSession, Workout, db
from .progression import TRAINING_WEEKDAYS

ABSENT = "absent"
RATE = "rate"
KINDS = (ABSENT, RATE)


def _done_days():
    """Les dates auxquelles une séance a été terminée."""
    return {w.date.date() for w in Workout.query.filter_by(completed=True)
            if w.date is not None}


def _qualifications():
    return {m.date: m for m in MissedSession.query.all()}


def planned_days(start, end):
    """Les jours d'entraînement planifiés de start à end inclus."""
    day = start
    while day <= end:
        if day.weekday() in TRAINING_WEEKDAYS:
            yield day
        day += timedelta(days=1)


def missed(today=None):
    """Jours d'entraînement passés sans séance faite, du plus récent au plus ancien.

    Chaque entrée porte sa qualification : {"date", "kind", "note"}, kind
    valant None tant que rien n'a été déclaré.

    L'historique commence à la première séance faite. Avant elle, il n'y avait
    pas de programme à manquer — remonter plus loin inventerait des centaines
    de séances ratées qui n'ont jamais existé.
    """
    today = today or date.today()
    done = _done_days()
    if not done:
        return []
    quals = _qualifications()

    out = []
    # Le jour même n'est pas manqué : la séance peut encore avoir lieu.
    for day in planned_days(min(done), today - timedelta(days=1)):
        if day in done:
            continue
        m = quals.get(day)
        out.append({"date": day,
                    "kind": m.kind if m else None,
                    "note": m.note if m else None})
    out.reverse()
    return out


def qualify(day, kind, note=None):
    """Déclare pourquoi un jour a été manqué. Repasser deux fois écrase."""
    if kind not in KINDS:
        raise ValueError("qualification inconnue : {!r}".format(kind))
    entry = MissedSession.query.filter_by(date=day).first()
    if entry is None:
        entry = MissedSession(date=day)
        db.session.add(entry)
    entry.kind = kind
    entry.note = note or None
    db.session.commit()
    return entry


def unqualify(day):
    """Annule une déclaration : le jour redevient « à qualifier »."""
    entry = MissedSession.query.filter_by(date=day).first()
    if entry is not None:
        db.session.delete(entry)
        db.session.commit()


def summary(today=None):
    """Ce que le coach a besoin de savoir, en une passe.

    `streak` ne compte que les séances manquées ET non excusées depuis la
    dernière séance faite : c'est la seule mesure qui décrit un relâchement.
    Compter les jours calendaires ferait dire « 21 jours sans séance » à
    quelqu'un qui rentre de vacances.
    """
    items = missed(today)
    absents = [m for m in items if m["kind"] == ABSENT]
    rates = [m for m in items if m["kind"] == RATE]
    todo = [m for m in items if m["kind"] is None]

    # Série en cours : on remonte du plus récent tant que ce n'est pas excusé.
    # Un jour non qualifié interrompt le décompte au lieu de l'alimenter —
    # dans le doute, le coach se tait.
    streak = 0
    for m in items:
        if m["kind"] == RATE:
            streak += 1
        else:
            break

    # Le plus long enchaînement de séances ratées de l'histoire, absences
    # exclues : c'est ce qui coûte le plus cher à la progression.
    longest = run = 0
    for m in reversed(items):
        run = run + 1 if m["kind"] == RATE else 0
        longest = max(longest, run)

    # Les non qualifiées en tête : ce sont les seules qui attendent quelque
    # chose. Le tri se fait ICI et pas dans le gabarit — Jinja compare `kind`
    # brut, et mélanger None et texte lève un TypeError dès la première
    # qualification.
    ordered = sorted(items, key=lambda m: (m["kind"] is not None, m["kind"] or "",
                                           -m["date"].toordinal()))

    return {"missed": ordered, "absent": len(absents), "rate": len(rates),
            "todo": len(todo), "streak": streak, "longest": longest}


def backfill_absences(today=None):
    """Marque « absent » tout jour manqué encore non qualifié.

    Rattrapage unique, pour une base créée avant que la distinction existe :
    à ce moment-là tous les trous venaient de vacances ou de déplacements.
    N'écrase jamais une qualification existante, et ne s'exécute que si la
    table est vide — sinon un déploiement plus tard requalifierait en absence
    des séances honnêtement ratées.
    """
    if MissedSession.query.first() is not None:
        return 0
    items = [m for m in missed(today) if m["kind"] is None]
    for m in items:
        db.session.add(MissedSession(date=m["date"], kind=ABSENT,
                                     note="rattrapage automatique"))
    if items:
        db.session.commit()
    return len(items)
