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


class ProgramExercise(db.Model):
    """Exercice du programme PPL, avec sa charge de travail courante.

    La charge évolue automatiquement (double progression) quand une séance
    est terminée. Pour les tractions assistées, la charge représente
    l'assistance : increment_kg est négatif pour qu'une progression la réduise.
    """
    __tablename__ = "program_exercises"
    id = db.Column(db.Integer, primary_key=True)
    session_type = db.Column(db.String(10), nullable=False)  # push/pull/legs
    position = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(60), nullable=False)  # static/img/exercises/<slug>.svg
    sets = db.Column(db.Integer, default=4)
    rep_min = db.Column(db.Integer)
    rep_max = db.Column(db.Integer)
    weight_kg = db.Column(db.Float, default=0)
    increment_kg = db.Column(db.Float, default=2.5)
    rest_sec = db.Column(db.Integer, default=60)
    notes = db.Column(db.String(200))
    sets_logged = db.relationship("ExerciseSet", backref="program_exercise")
