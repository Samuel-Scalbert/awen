"""Stockage des récaps de fin de session Claude Code.

Un récap par projet, écrasé à chaque fin de session : ce qui intéresse ici
c'est l'état courant — « où on s'est arrêté » — pas l'historique. L'histoire
des commits est dans git, celle des conversations dans Claude Code.

Les récaps vivent dans le volume `data/` plutôt qu'en base : un récap est un
document opaque poussé par le PC, il n'a aucune relation à modéliser, et on
veut pouvoir le lire au `cat` quand quelque chose cloche. Une image
reconstruite ne les emporte pas, le volume est monté hors du conteneur.
"""
import json
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app

# Le nom de projet arrive du réseau et sert de nom de fichier : on le
# contraint plutôt que de l'assainir, c'est le PC qui l'envoie et il n'a
# aucune raison d'être exotique.
_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Au-delà, le récap décrit un état que le dépôt a sûrement dépassé. On
# l'affiche quand même, marqué périmé : un projet qu'on n'a pas touché depuis
# deux semaines est une information en soi.
STALE_AFTER_DAYS = 14

_LIST_FIELDS = ("done", "next", "blockers")
_TEXT_FIELDS = ("branch", "stopped_at", "last_commit", "host")


def recaps_dir():
    base = Path(current_app.config["DEV_RECAP_DIR"])
    base.mkdir(parents=True, exist_ok=True)
    return base


def _clean_list(value, max_items=8, max_len=200):
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if not isinstance(item, str):
            continue
        item = " ".join(item.split())
        if item:
            out.append(item[:max_len])
        if len(out) >= max_items:
            break
    return out


def normalise(payload):
    """Garde les seuls champs connus, bornés en taille. None si inexploitable.

    On ne fait pas confiance au corps de la requête pour la taille : un
    journal entier poussé par erreur dans `stopped_at` remplirait le volume.
    """
    if not isinstance(payload, dict):
        return None
    project = payload.get("project")
    if not isinstance(project, str) or not _SLUG_RE.match(project):
        return None

    recap = {"project": project}
    for field in _TEXT_FIELDS:
        value = payload.get(field)
        recap[field] = " ".join(value.split())[:200] if isinstance(value, str) else ""
    for field in _LIST_FIELDS:
        recap[field] = _clean_list(payload.get(field))

    dirty = payload.get("dirty")
    recap["dirty"] = dirty if isinstance(dirty, int) and 0 <= dirty < 10000 else 0

    # L'horodatage est posé par le serveur : l'heure du PC n'est pas
    # forcément juste, et c'est « quand le récap est arrivé » qui compte
    # pour décider s'il est périmé.
    recap["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return recap


def save_recap(payload):
    """Écrit le récap d'un projet. Renvoie le récap normalisé, ou None."""
    recap = normalise(payload)
    if recap is None:
        return None
    target = recaps_dir() / f"{recap['project']}.json"
    # Écriture par fichier temporaire puis remplacement : PhoneBox relit
    # toutes les N secondes et ne doit jamais tomber sur un JSON à moitié
    # écrit. os.replace est atomique sur le même système de fichiers.
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(recap, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return recap


def _age_days(recap):
    try:
        updated = datetime.fromisoformat(recap["updated"])
    except (KeyError, TypeError, ValueError):
        return None
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - updated).total_seconds() / 86400


def load_recaps():
    """Tous les récaps, le plus récemment mis à jour d'abord."""
    recaps = []
    for f in sorted(recaps_dir().glob("*.json")):
        try:
            recap = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(recap, dict):
            continue
        age = _age_days(recap)
        recap["age_days"] = round(age, 1) if age is not None else None
        recap["stale"] = age is not None and age > STALE_AFTER_DAYS
        recaps.append(recap)
    recaps.sort(key=lambda r: r.get("updated") or "", reverse=True)
    return recaps


def _fit(text, width):
    """Tronque sur une frontière de mot : « sur le calend » se lit mal."""
    if len(text) <= width:
        return text
    cut = text[:width - 2]
    space = cut.rfind(" ")
    if space > width // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + ".."


LARGEUR_MIN, LARGEUR_MAX = 20, 120
LIGNES_PAR_POINT = 3


def _plier(prefixe, texte, width):
    """Une tâche sur plusieurs lignes plutôt que coupée : « Mettre a jour le
    clone de.. » ne dit plus rien. Les suites s'alignent sous le texte ; au
    delà de trois lignes, la dernière est tronquée."""
    retrait = " " * len(prefixe)
    lignes = textwrap.wrap(texte, width=width, initial_indent=prefixe,
                           subsequent_indent=retrait, break_long_words=True)
    if len(lignes) > LIGNES_PAR_POINT:
        reste = " ".join(lignes[LIGNES_PAR_POINT - 1:]).strip()
        lignes = lignes[:LIGNES_PAR_POINT - 1] + [_fit(retrait + reste, width)]
    return lignes


def board_text(width=34, max_next=2):
    """Rendu texte compact, pour le widget Command de PhoneBox.

    Pré-formaté ici et pas côté téléphone : le widget ne sait qu'afficher la
    sortie d'une commande, et une seule requête HTTP coûte moins qu'un bout
    de logique à maintenir sur l'Android. Les tâches reviennent à la ligne ;
    `width` suit la largeur du widget (paramètre `largeur` de la route).
    """
    width = max(LARGEUR_MIN, min(int(width), LARGEUR_MAX))
    recaps = load_recaps()
    if not recaps:
        return "Aucun recap. Session Claude Code pas encore terminee ?"

    lines = []
    for recap in recaps:
        head = recap.get("project", "?")
        if recap.get("branch"):
            head += f" · {recap['branch']}"
        if recap.get("dirty"):
            head += f" · {recap['dirty']} fich."
        if recap.get("stale"):
            head += " · perime"
        lines.append(_fit(head, width))

        for item in recap.get("next", [])[:max_next]:
            lines += _plier("  -> ", item, width)
        for item in recap.get("blockers", [])[:1]:
            lines += _plier("  !! ", item, width)
        if not recap.get("next") and not recap.get("blockers"):
            lines.append("  -> rien en cours")
        lines.append("")
    return "\n".join(lines).rstrip()
