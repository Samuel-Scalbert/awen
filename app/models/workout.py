from datetime import datetime
from . import db


class Workout(db.Model):
    __tablename__ = "workouts"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    focus = db.Column(db.String(80))  # Push / Pull / Legs
    notes = db.Column(db.Text)
    completed = db.Column(db.Boolean, default=False)
    sets = db.relationship("ExerciseSet", backref="workout",
                           cascade="all, delete-orphan")
    notes_by_exercise = db.relationship("ExerciseNote", backref="workout",
                                        cascade="all, delete-orphan")


class ExerciseSet(db.Model):
    __tablename__ = "exercise_sets"
    id = db.Column(db.Integer, primary_key=True)
    workout_id = db.Column(db.Integer, db.ForeignKey("workouts.id"))
    program_exercise_id = db.Column(
        db.Integer, db.ForeignKey("program_exercises.id"), nullable=True)
    exercise = db.Column(db.String(120), nullable=False)
    set_number = db.Column(db.Integer)
    reps = db.Column(db.Integer)
    weight_kg = db.Column(db.Float)
    # Reps en réserve : combien il en restait avant l'échec. C'est la seule
    # mesure de l'effort réel — 12 reps à 3 en réserve et 12 reps à l'échec
    # n'ont pas du tout la même signification, et sans ça l'app les confond.
    # Facultatif : None = non renseigné, on retombe sur les règles de reps.
    rir = db.Column(db.Integer)


class ExerciseNote(db.Model):
    """Commentaire libre sur un exercice, pour une séance donnée.

    Un seul par (séance, exercice) : on met à jour au lieu d'empiler, pour
    que la note reste le ressenti final de l'exercice ce jour-là (« épaule
    droite sensible », « machine réglée au cran 4 »…).
    """
    __tablename__ = "exercise_notes"
    __table_args__ = (db.UniqueConstraint("workout_id", "program_exercise_id",
                                          name="uq_note_workout_exercise"),)
    id = db.Column(db.Integer, primary_key=True)
    workout_id = db.Column(db.Integer, db.ForeignKey("workouts.id"), nullable=False)
    program_exercise_id = db.Column(db.Integer,
                                    db.ForeignKey("program_exercises.id"),
                                    nullable=False)
    text = db.Column(db.Text, default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)


class ProgramExercise(db.Model):
    """Exercice du programme PPL, avec sa charge de travail courante.

    La charge évolue automatiquement (double progression) quand une séance
    est terminée. Pour les tractions assistées, la charge représente
    l'assistance : increment_kg est négatif pour qu'une progression la réduise.
    """
    __tablename__ = "program_exercises"
    id = db.Column(db.Integer, primary_key=True)
    session_type = db.Column(db.String(10), nullable=False)  # push/pull/legs
    # "force" = travail avec charges, "plyo" = bloc pliométrique (saut). Les
    # deux ne se pilotent pas pareil : la plyo progresse en hauteur et en
    # qualité d'appui, jamais en kilos ajoutés.
    block = db.Column(db.String(10), default="force")
    position = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(60), nullable=False)  # static/img/exercises/<slug>.svg
    sets = db.Column(db.Integer, default=4)
    # "reps" = répétitions comptées, "sec" = série tenue au chrono (rebonds de
    # chevilles, gainage…). rep_min/rep_max portent alors des secondes.
    unit = db.Column(db.String(6), default="reps")
    rep_min = db.Column(db.Integer)
    rep_max = db.Column(db.Integer)
    weight_kg = db.Column(db.Float, default=0)
    increment_kg = db.Column(db.Float, default=2.5)
    rest_sec = db.Column(db.Integer, default=60)
    # Un exercice retiré du programme n'est pas supprimé : ses séries passées
    # restent rattachées et continuent d'alimenter les statistiques. Il
    # disparaît simplement des séances et de la page Programme.
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.String(200))
    sets_logged = db.relationship("ExerciseSet", backref="program_exercise")


class BodyWeight(db.Model):
    """Pesée hebdomadaire.

    Sans elle, impossible de distinguer « le programme ne marche pas » de
    « tu ne manges pas assez » : des charges qui stagnent alors que le poids
    stagne aussi, c'est un problème d'assiette, pas de programmation.
    """
    __tablename__ = "body_weights"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    weight_kg = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(200))


class JumpTest(db.Model):
    """Test de détente verticale — la mesure de l'objectif volley.

    La pliométrie s'entraîne pour sauter plus haut ; sans mesure régulière,
    aucune boucle de retour sur ce qu'on cherche réellement à améliorer.
    """
    __tablename__ = "jump_tests"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    height_cm = db.Column(db.Float, nullable=False)
    note = db.Column(db.String(200))


class CoachDecision(db.Model):
    """Journal des décisions du coach : quoi, quand, et surtout pourquoi.

    Toute modification automatique de charge est tracée ici pour être
    relisible et contestable — une progression qui change sans explication
    est une progression à laquelle on ne peut pas faire confiance.
    """
    __tablename__ = "coach_decisions"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    program_exercise_id = db.Column(db.Integer,
                                    db.ForeignKey("program_exercises.id"))
    workout_id = db.Column(db.Integer, db.ForeignKey("workouts.id"))
    kind = db.Column(db.String(24))        # progression / deload / recalage…
    reason = db.Column(db.String(300))
    old_weight = db.Column(db.Float)
    new_weight = db.Column(db.Float)
