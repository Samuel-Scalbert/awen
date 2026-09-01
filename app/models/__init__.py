"""Modèles de données Awen."""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from .workout import (BodyWeight, CoachDecision,  # noqa: E402,F401
                      ExerciseNote, ExerciseSet, JumpTest, MissedSession,
                      ProgramExercise, Workout)
from .meal import Recipe  # noqa: E402,F401
