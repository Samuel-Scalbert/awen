from datetime import datetime
from . import db


class Workout(db.Model):
    __tablename__ = "workouts"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    focus = db.Column(db.String(80))  # ex: Pecs/Triceps, Jambes...
    notes = db.Column(db.Text)
    sets = db.relationship("ExerciseSet", backref="workout",
                           cascade="all, delete-orphan")


class ExerciseSet(db.Model):
    __tablename__ = "exercise_sets"
    id = db.Column(db.Integer, primary_key=True)
    workout_id = db.Column(db.Integer, db.ForeignKey("workouts.id"))
    exercise = db.Column(db.String(120), nullable=False)
    reps = db.Column(db.Integer)
    weight_kg = db.Column(db.Float)
