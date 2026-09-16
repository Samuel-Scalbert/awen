"""Les tâches, vues comme un service — parce que trois clients les lisent.

L'interface web, l'ESP32 et Jarvis veulent tous la même liste. Écrire la
requête trois fois, c'est trois endroits où l'ordre de tri finira par diverger
et où « mes prochaines tâches » ne désignera plus la même chose selon l'écran
qu'on regarde.

C'EST LE SEUL ENDROIT OÙ JARVIS ÉCRIT

Partout ailleurs le modèle ne fait que lire. Le jour où il peut enregistrer
une séance, il peut aussi en inventer une, et une base d'entraînement faussée
ne se répare pas : on ne sait plus quelle ligne est vraie. Une tâche inventée,
elle, se voit tout de suite et s'efface en un clic — le risque est nul et
l'usage quotidien. D'où `add()` et `complete()` ici, et rien de plus : pas de
suppression, terminer suffit et garde la trace.
"""
from datetime import date, datetime

from ..models import Todo, db

MAX_LEN = 200


def pending(limit=None):
    """Les tâches à faire : les datées d'abord, par échéance, puis les autres.

    SQLite place NULL en tête d'un tri croissant. Sans le premier critère,
    les tâches sans échéance passeraient donc *avant* celle qui tombe demain,
    ce qui est exactement l'inverse de ce qu'on veut lire.
    """
    q = (Todo.query.filter_by(done=False)
         .order_by((Todo.due.is_(None)).asc(), Todo.due.asc(), Todo.id.asc()))
    return q.limit(limit).all() if limit else q.all()


def done(limit=30):
    return (Todo.query.filter_by(done=True)
            .order_by(Todo.done_at.desc()).limit(limit).all())


def counts():
    total = Todo.query.filter_by(done=False).count()
    late = sum(1 for t in pending() if t.due and t.due < date.today())
    return {"pending": total, "late": late}


def add(text, due=None, source="web"):
    """Crée une tâche. Renvoie None si le texte est vide.

    Le texte est tronqué plutôt que refusé : une tâche dictée un peu longue
    vaut mieux perdue à la fin que perdue en entier.
    """
    text = (text or "").strip()
    if not text:
        return None
    entry = Todo(text=text[:MAX_LEN], due=due, source=source)
    db.session.add(entry)
    db.session.commit()
    return entry


def complete(todo_id, undo=False):
    """Coche ou décoche. Réversible, toujours."""
    entry = db.session.get(Todo, int(todo_id))
    if entry is None:
        return None
    entry.done = not undo
    entry.done_at = None if undo else datetime.now()
    db.session.commit()
    return entry


def complete_by_text(fragment):
    """Termine la première tâche dont le texte contient ce fragment.

    Pour Jarvis et le pavé : dicter « terminer les courses » est naturel,
    retenir l'identifiant 47 ne l'est pas. On ne touche qu'à une seule tâche
    même si plusieurs correspondent — en cocher trois d'un coup sur une
    correspondance approximative serait pire que de n'en cocher aucune.
    """
    frag = (fragment or "").strip().lower()
    if not frag:
        return None
    for t in pending():
        if frag in t.text.lower():
            return complete(t.id)
    return None


def lines(limit=3, width=30):
    """Les prochaines tâches, prêtes à dessiner sur l'afficheur.

    Formaté ici et pas sur l'ESP32 : la carte interprète du MicroPython, tout
    ce qu'on prépare est autant de travail qu'elle n'a pas à faire.
    """
    out = []
    for t in pending(limit):
        marque = "!" if t.due and t.due < date.today() else "-"
        out.append("{} {}".format(marque, t.text)[:width])
    return out
