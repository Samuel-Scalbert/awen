from datetime import datetime

from . import db


class Todo(db.Model):
    """Une tâche. Volontairement pauvre en champs.

    Pas de priorité, pas d'étiquettes, pas de sous-tâches : une liste de
    choses à faire qui demande elle-même dix minutes d'entretien par jour
    finit abandonnée, et une tâche non notée ne vaut rien.

    `source` dit par où la tâche est entrée — l'interface, Jarvis ou le pavé
    numérique. Ce n'est pas décoratif : au bout d'un mois, il dira lequel des
    trois chemins sert vraiment, et lesquels on peut cesser d'entretenir.
    """
    __tablename__ = "todos"

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(200), nullable=False)
    done = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    done_at = db.Column(db.DateTime)
    # Facultative : une échéance obligatoire pousse à en inventer, et une
    # date inventée ne veut plus rien dire quand elle arrive.
    due = db.Column(db.Date)
    source = db.Column(db.String(12), default="web")
