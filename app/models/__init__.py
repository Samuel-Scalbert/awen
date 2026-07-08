"""Modèles de données Awen."""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from .workout import Workout, ExerciseSet  # noqa: E402,F401
from .meal import Recipe  # noqa: E402,F401
