"""Modèles de données Awen."""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

from .workout import (BodyWeight, CoachDecision,  # noqa: E402,F401
                      DataMigration, ExerciseNote, ExerciseSet, JumpTest,
                      MissedSession, ProgramExercise, WeeklyBrief,
                      Workout)
from .meal import Recipe  # noqa: E402,F401
from .todo import Todo  # noqa: E402,F401
from .lettre import CoverLetter, LetterLesson, OffreRattrapee  # noqa: E402,F401
from .levee import CollecteLevees, Levee, MailProspection  # noqa: E402,F401
