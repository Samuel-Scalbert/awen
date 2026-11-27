"""Le bilan du dimanche : Claude relit la semaine et prépare la suivante.

Le coach à règles (coach.py) et la double progression (progression.py)
règlent déjà les charges séance après séance. Ce bilan fait ce qu'aucune
règle ne sait faire :

- lire les commentaires de salle comme des consignes ;
- voir la semaine entière (une séance ratée, plusieurs exercices qui
  stagnent ensemble, un poids qui ne bouge pas) ;
- relire le bilan précédent pour dire si ses conseils ont marché ;
- juger, sur plusieurs semaines, s'il est temps d'une semaine de décharge ;
- poser une question, une seule, à laquelle Samuel répond dans l'app.

Même règle que le coach : CLAUDE PROPOSE, SAMUEL APPLIQUE. Les charges
proposées passent par le bouton « Appliquer » de la page Coach, journalisé
dans CoachDecision. Claude ne change jamais d'exercice : le schéma de sa
réponse n'a pas de place pour ça.

Lancé chaque dimanche soir sur le serveur (scripts/install-coach-hebdo.sh)
par `flask --app run coach-hebdo`. Claude Code tourne avec l'abonnement,
comme pour les lettres. S'il ne répond pas, le bilan se replie sur les
observations du coach à règles : il y a toujours quelque chose à lire lundi.
"""
import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

import click
from flask.cli import with_appcontext

from ..models import (BodyWeight, CoachDecision, ExerciseNote, JumpTest,
                      ProgramExercise, WeeklyBrief, Workout, db)
from . import attendance, coach
from .charges import from_display, label, shown, snap
from .progression import PLYO, REPRISE, TRAINING_WEEKDAYS, upcoming

SKILL = (Path(__file__).resolve().parents[2]
         / ".claude" / "skills" / "coach-hebdo" / "SKILL.md")

SEMAINES = 6          # recul pour la vue d'ensemble et le cycle
HISTORIQUE = 6        # séances d'historique montrées par exercice
COMMENTAIRES_JOURS = 21
PROPOSITIONS_MAX = 4
# Une charge qui bouge de plus d'un quart n'est pas un ajustement, c'est une
# erreur de lecture : elle est écartée plutôt que proposée.
ECART_MAX = 0.25
CONSIGNES_MAX = 3
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

SCHEMA = {
    "type": "object",
    "properties": {
        "bilan": {"type": "string"},
        "suivi": {"type": "string"},
        "prochaine_seance": {"type": "array", "items": {"type": "string"}},
        "charges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "exercice_id": {"type": "integer"},
                    "charge": {"type": "number"},
                    "raison": {"type": "string"},
                },
                "required": ["exercice_id", "charge", "raison"],
                "additionalProperties": False,
            },
        },
        "cycle": {
            "type": "object",
            "properties": {
                "decharge": {"type": "boolean"},
                "pourquoi": {"type": "string"},
            },
            "required": ["decharge", "pourquoi"],
            "additionalProperties": False,
        },
        "question": {"type": "string"},
    },
    "required": ["bilan", "suivi", "prochaine_seance", "charges", "cycle",
                 "question"],
    "additionalProperties": False,
}


class CoachHebdoErreur(Exception):
    pass


# --------------------------------------------------------------------------
# La semaine relue
# --------------------------------------------------------------------------

def semaine_relue(today=None):
    """Le lundi de la semaine à relire.

    Le dimanche, c'est la semaine qui s'achève. Un autre jour (le serveur
    était éteint dimanche soir et le timer rattrape lundi matin, ou on le
    lance à la main), c'est la dernière semaine complète.
    """
    today = today or date.today()
    demain = today + timedelta(days=1)
    return demain - timedelta(days=demain.weekday() + 7)


def _debut(jour):
    return datetime.combine(jour, time.min)


def _faites(debut, fin):
    """Séances terminées avec au moins une série, de debut à fin exclu."""
    return [w for w in (Workout.query.filter_by(completed=True)
                        .filter(Workout.date >= _debut(debut),
                                Workout.date < _debut(fin))
                        .order_by(Workout.date))
            if w.sets]


def _charge(kg, pe):
    """Le nombre lu sur la machine, celui que Samuel tape et reconnaît."""
    return shown(kg, pe) if pe is not None else round(kg or 0, 2)


def _exercice(pe):
    out = {
        "id": pe.id, "nom": pe.name, "seance": pe.session_type,
        "bloc": pe.block, "series": pe.sets, "unite": pe.unit,
        "fourchette": [pe.rep_min, pe.rep_max],
    }
    if pe.block != "plyo" and pe.weight_kg:
        out["charge"] = _charge(pe.weight_kg, pe)
    if pe.block != "plyo" and pe.increment_kg and pe.weight_kg:
        # Les crans voisins : Claude propose une charge qui existe sur la
        # machine plutôt qu'un nombre rond qu'il faudrait arrondir.
        out["un_cran_plus_dur"] = _charge(coach._harder(pe), pe)
        out["un_cran_plus_facile"] = _charge(coach._easier(pe), pe)
        out["assistance"] = pe.increment_kg < 0
    return out


def _seance(w):
    notes = {n.program_exercise_id: n.text for n in w.notes_by_exercise
             if (n.text or "").strip()}
    exercices, index = [], {}
    for s in sorted(w.sets, key=lambda s: s.id):
        pe = s.program_exercise
        cle = s.program_exercise_id or s.exercise
        if cle not in index:
            index[cle] = {"id": s.program_exercise_id, "nom": s.exercise,
                          "series": []}
            if s.program_exercise_id in notes:
                index[cle]["commentaire"] = notes[s.program_exercise_id]
            exercices.append(index[cle])
        serie = {"reps": s.reps, "charge": _charge(s.weight_kg, pe)}
        if s.rir is not None:
            serie["rir"] = s.rir
        index[cle]["series"].append(serie)
    out = {"date": w.date.date().isoformat(), "jour": JOURS[w.date.weekday()],
           "seance": w.focus, "exercices": exercices}
    if (w.notes or "").strip():
        out["note"] = w.notes.strip()
    return out


def _historique(actifs):
    completed = {w.id: w.date.date()
                 for w in Workout.query.filter_by(completed=True)
                 if w.focus != REPRISE}
    out = {}
    for pe in actifs:
        if pe.block == "plyo":
            continue
        hist = coach._sessions_of(pe, completed)[-HISTORIQUE:]
        if hist:
            out[str(pe.id)] = [
                {"date": h["date"].isoformat(),
                 "charge": _charge(h["weight"], pe),
                 "reps": h["reps"], "rir": h["rir"]} for h in hist]
    return out


def _tendance(lundi):
    """Les SEMAINES dernières, de la plus ancienne à celle qu'on relit."""
    out = []
    for k in range(SEMAINES - 1, -1, -1):
        debut = lundi - timedelta(weeks=k)
        fin = debut + timedelta(days=7)
        faites = _faites(debut, fin)
        out.append({
            "semaine": debut.isoformat(),
            "seances": len(faites),
            "prevues": len(list(attendance.planned_days(debut, fin - timedelta(days=1)))),
            "volume_kg": round(sum((s.reps or 0) * (s.weight_kg or 0)
                                   for w in faites for s in w.sets)),
            "rir_moyen": _moyenne([s.rir for w in faites for s in w.sets
                                   if s.rir is not None]),
        })
    return out


def _moyenne(valeurs):
    return round(sum(valeurs) / len(valeurs), 1) if valeurs else None


def _observations():
    out = []
    for a in coach.analyse():
        o = {"niveau": a["level"], "titre": a["title"], "detail": a["detail"]}
        if a.get("action") == "set_weight":
            o["charge_proposee"] = label(a["new_weight"], a["exercise"])
        out.append(o)
    return out


def _commentaires(today):
    depuis = _debut(today - timedelta(days=COMMENTAIRES_JOURS))
    out = []
    for w in (Workout.query.filter(Workout.date >= depuis)
              .order_by(Workout.date)):
        if (w.notes or "").strip():
            out.append({"date": w.date.date().isoformat(), "seance": w.focus,
                        "texte": w.notes.strip()})
        for n in w.notes_by_exercise:
            if (n.text or "").strip():
                pe = db.session.get(ProgramExercise, n.program_exercise_id)
                out.append({"date": w.date.date().isoformat(),
                            "exercice": pe.name if pe else None,
                            "exercice_id": n.program_exercise_id,
                            "texte": n.text.strip()})
    return out


def _decisions(depuis):
    out = []
    for d in (CoachDecision.query.filter(CoachDecision.created_at >= depuis)
              .order_by(CoachDecision.created_at)):
        pe = db.session.get(ProgramExercise, d.program_exercise_id)
        out.append({
            "date": d.created_at.date().isoformat(), "type": d.kind,
            "exercice": pe.name if pe else None,
            "avant": _charge(d.old_weight, pe) if d.old_weight is not None else None,
            "apres": _charge(d.new_weight, pe) if d.new_weight is not None else None,
            "raison": d.reason,
        })
    return out


def _a_venir(dimanche):
    from ..routes.workout import exercises_for
    out = []
    for jour, focus in upcoming(dimanche, count=3):
        out.append({
            "date": jour.isoformat(), "jour": JOURS[jour.weekday()],
            "seance_suggeree": focus,
            "exercices": [_exercice(pe) for pe in exercises_for(focus)],
        })
    return out


def _precedent(lundi):
    """Le dernier bilan avant celui-ci, et ce qu'il en est advenu."""
    b = (WeeklyBrief.query.filter(WeeklyBrief.semaine < lundi)
         .order_by(WeeklyBrief.semaine.desc()).first())
    if b is None:
        return None
    c = b.contenu or {}
    return {
        "semaine": b.semaine.isoformat(), "source": b.source,
        "bilan": c.get("bilan"), "prochaine_seance": c.get("prochaine_seance"),
        "cycle": c.get("cycle"),
        "charges": [dict(p, appliquee=p_appliquee(b, p))
                    for p in c.get("charges", [])],
        "question": b.question or None, "reponse": b.reponse,
    }


def _cycle(lundi):
    """Les semaines de décharge conseillées par les bilans passés."""
    briefs = (WeeklyBrief.query.filter(WeeklyBrief.semaine < lundi)
              .order_by(WeeklyBrief.semaine.desc()).limit(12).all())
    decharges = [b.semaine for b in briefs
                 if (b.contenu or {}).get("cycle", {}).get("decharge")]
    return {
        "bilans_precedents": len(briefs),
        "derniere_decharge_conseillee": decharges[0].isoformat() if decharges else None,
        "semaines_depuis": ((lundi - decharges[0]).days // 7) if decharges else None,
    }


def dossier(lundi, today=None):
    """Tout ce que Claude lit, en un seul objet JSON."""
    today = today or date.today()
    dimanche = lundi + timedelta(days=6)
    fin = lundi + timedelta(days=7)
    actifs = (ProgramExercise.query.filter(ProgramExercise.active.is_(True))
              .order_by(ProgramExercise.session_type, ProgramExercise.position)
              .all())
    manquees = [{"date": m["date"].isoformat(), "jour": JOURS[m["date"].weekday()],
                 "qualification": m["kind"] or "non qualifiee",
                 "note": m["note"]}
                for m in attendance.missed(today)
                if lundi <= m["date"] <= dimanche]
    pesees = BodyWeight.query.order_by(BodyWeight.date.desc()).limit(8).all()
    sauts = JumpTest.query.order_by(JumpTest.date.desc()).limit(3).all()
    return {
        "aujourdhui": today.isoformat(),
        "semaine": {"du": lundi.isoformat(), "au": dimanche.isoformat(),
                    "jours_prevus": [JOURS[d] for d in TRAINING_WEEKDAYS]},
        "seances": [_seance(w) for w in _faites(lundi, fin)],
        "seances_manquees": manquees,
        "programme": [_exercice(pe) for pe in actifs],
        "historique_par_exercice": _historique(actifs),
        "tendance": _tendance(lundi),
        "observations_du_coach_a_regles": _observations(),
        "commentaires_recents": _commentaires(today),
        "decisions_de_charge": _decisions(_debut(lundi)),
        "poids_de_corps": [{"date": p.date.isoformat(), "kg": p.weight_kg}
                           for p in reversed(pesees)],
        "detente": [{"date": s.date.isoformat(), "cm": s.height_cm}
                    for s in reversed(sauts)],
        "prochaines_seances": _a_venir(dimanche),
        "bilan_precedent": _precedent(lundi),
        "cycle": _cycle(lundi),
    }


# --------------------------------------------------------------------------
# Claude, puis ce qu'on garde de sa réponse
# --------------------------------------------------------------------------

def consignes():
    """Le corps du skill, sans son en-tête : relu à chaque bilan."""
    try:
        texte = SKILL.read_text(encoding="utf-8")
    except OSError:
        raise CoachHebdoErreur("Le skill du coach est introuvable ({}).".format(SKILL))
    morceaux = re.split(r"^---\s*$", texte, maxsplit=2, flags=re.M)
    return (morceaux[2] if texte.startswith("---") and len(morceaux) == 3
            else texte).strip()


def _demander(d):
    # Même appel que les lettres : abonnement, aucun outil, rien de la
    # configuration du compte, réflexion plafonnée.
    from .lettres import LettreErreur, _appel_claude_code
    message = ("<dossier>\n{}\n</dossier>\n\nÉcris le bilan de la semaine du {} "
               "au {}.").format(json.dumps(d, ensure_ascii=False, indent=1),
                                d["semaine"]["du"], d["semaine"]["au"])
    try:
        data, _usage = _appel_claude_code(consignes(), message, SCHEMA,
                                          effort="medium")
    except LettreErreur as e:
        raise CoachHebdoErreur(str(e))
    return data


def _texte(v, n=1200):
    return " ".join(str(v or "").split())[:n]


def _charges_valides(propositions):
    """Ne garde que les charges qu'on peut appliquer telles quelles.

    Un exercice actif, avec une charge ; la valeur lue sur la machine ramenée
    sur un cran ; différente de l'actuelle ; et un écart raisonnable. Le
    reste est écarté sans bruit : mieux vaut une proposition de moins qu'un
    bouton qui mettrait 300 kg sur la presse.
    """
    out, vus = [], set()
    for p in propositions or []:
        pe = db.session.get(ProgramExercise, p.get("exercice_id"))
        if (pe is None or not pe.active or pe.block == "plyo"
                or not pe.weight_kg or pe.id in vus):
            continue
        try:
            kg = snap(from_display(float(p.get("charge")), pe), pe)
        except (TypeError, ValueError):
            continue
        if abs(kg - pe.weight_kg) < 1e-6 or kg <= 0:
            continue
        if abs(kg - pe.weight_kg) / pe.weight_kg > ECART_MAX:
            continue
        vus.add(pe.id)
        out.append({"exercice_id": pe.id, "charge_kg": kg,
                    "raison": _texte(p.get("raison"), 300)})
        if len(out) == PROPOSITIONS_MAX:
            break
    return out


def _nettoie(data):
    cycle = data.get("cycle") or {}
    return {
        "bilan": _texte(data.get("bilan")),
        "suivi": _texte(data.get("suivi")),
        "prochaine_seance": [_texte(c, 300) for c in
                             (data.get("prochaine_seance") or [])
                             if _texte(c)][:CONSIGNES_MAX],
        "charges": _charges_valides(data.get("charges")),
        "cycle": {"decharge": bool(cycle.get("decharge")),
                  "pourquoi": _texte(cycle.get("pourquoi"), 400)},
    }


def _repli(d):
    """Sans Claude : les observations du coach à règles, mises en forme."""
    derniere = d["tendance"][-1]
    obs = coach.analyse()
    return {
        "bilan": "{} séance{} sur {} prévues cette semaine.".format(
            derniere["seances"], "s" if derniere["seances"] > 1 else "",
            derniere["prevues"]),
        "suivi": "",
        "prochaine_seance": [a["title"] for a in obs
                             if a["level"] in ("alert", "warn")][:CONSIGNES_MAX],
        "charges": [{"exercice_id": a["exercise"].id,
                     "charge_kg": a["new_weight"],
                     "raison": _texte(a["detail"], 300)}
                    for a in obs if a.get("action") == "set_weight"
                    ][:PROPOSITIONS_MAX],
        "cycle": {"decharge": False, "pourquoi": ""},
    }


def generer(today=None, refaire=False):
    """Écrit le bilan de la semaine relue. Renvoie (bilan, cree)."""
    today = today or date.today()
    lundi = semaine_relue(today)
    existant = WeeklyBrief.query.filter_by(semaine=lundi).first()
    if existant is not None and existant.source == "claude" and not refaire:
        return existant, False

    d = dossier(lundi, today)
    try:
        data = _demander(d)
        contenu, source, erreur = _nettoie(data), "claude", None
        question = _texte(data.get("question"), 400)
    except CoachHebdoErreur as e:
        if existant is not None and existant.source == "claude":
            # Une relance ratée ne remplace pas un bon bilan par le repli.
            raise
        contenu, source, erreur, question = _repli(d), "regles", str(e)[:300], ""

    b = existant or WeeklyBrief(semaine=lundi)
    if existant is None:
        db.session.add(b)
    b.created_at = datetime.now()
    b.source, b.contenu, b.erreur = source, contenu, erreur
    if question != (b.question or ""):
        b.question, b.reponse, b.repondu_at = question, None, None
    db.session.commit()
    return b, True


# --------------------------------------------------------------------------
# Lecture, pour les pages
# --------------------------------------------------------------------------

def p_appliquee(b, p):
    """La charge proposée a-t-elle été appliquée depuis le bilan ?

    On compte à partir du dimanche de la semaine relue, pas de l'heure du
    bilan : CoachDecision date en UTC, le bilan en heure de Paris, et une
    charge appliquée dix minutes après le bilan paraîtrait antérieure.
    """
    return CoachDecision.query.filter(
        CoachDecision.program_exercise_id == p["exercice_id"],
        CoachDecision.created_at >= _debut(b.semaine + timedelta(days=6)),
        CoachDecision.new_weight.between(p["charge_kg"] - 1e-3,
                                         p["charge_kg"] + 1e-3)).first() is not None


def dernier(today=None, jours=8):
    """Le bilan le plus récent, s'il a moins de `jours` jours."""
    today = today or date.today()
    b = WeeklyBrief.query.order_by(WeeklyBrief.semaine.desc()).first()
    if b is None or (today - b.created_at.date()).days > jours:
        return None
    return b


def propositions(b):
    """Les charges proposées, prêtes pour le gabarit."""
    out = []
    for p in (b.contenu or {}).get("charges", []):
        pe = db.session.get(ProgramExercise, p["exercice_id"])
        if pe is None:
            continue
        out.append({"exercise": pe, "new_weight": p["charge_kg"],
                    "raison": p["raison"],
                    "faite": abs((pe.weight_kg or 0) - p["charge_kg"]) < 1e-3})
    return out


def repondre(b, texte):
    b.reponse = _texte(texte, 1000) or None
    b.repondu_at = datetime.now() if b.reponse else None
    db.session.commit()


@click.command("coach-hebdo")
@click.option("--refaire", is_flag=True,
              help="Réécrire le bilan même s'il existe déjà.")
@with_appcontext
def commande(refaire):
    """Écrit le bilan du dimanche (lancé par le timer du serveur)."""
    try:
        b, cree = generer(refaire=refaire)
    except CoachHebdoErreur as e:
        raise click.ClickException("Claude indisponible ({}) : le bilan "
                                   "existant est gardé.".format(e))
    if not cree:
        click.echo("Bilan de la semaine du {} déjà écrit : rien à faire "
                   "(--refaire pour le réécrire).".format(b.semaine))
        return
    if b.source == "claude":
        click.echo("Bilan de la semaine du {} écrit par Claude.".format(b.semaine))
    else:
        click.echo("Claude indisponible ({}) : bilan des règles seules."
                   .format(b.erreur))
