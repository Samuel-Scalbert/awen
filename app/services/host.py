"""État de la machine, lu depuis le fichier déposé par scripts/host-status.sh.

Awen n'interroge pas Docker lui-même : cela imposerait de lui monter
/var/run/docker.sock, qui donne le contrôle total du démon — de quoi sortir
du conteneur et devenir root sur l'hôte. Pour une ligne d'état, c'est hors de
proportion. Un script tourne donc sur l'hôte et dépose un fichier ; ici on ne
fait que le lire.
"""
import json
import time
from pathlib import Path

from flask import current_app

STALE_S = 300      # au-delà, le relevé n'est plus crédible


def _path():
    return Path(current_app.config["BASE_DIR"]) / "data" / "host-status.json"


def status():
    """Le dernier relevé, ou None s'il est absent ou périmé.

    Un relevé vieux de dix minutes est pire qu'aucun : il affirmerait que
    tout va bien alors que c'est justement le releveur qui est tombé. On
    préfère ne rien dire.
    """
    try:
        raw = _path().read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return None

    age = time.time() - data.get("at", 0)
    if age > STALE_S:
        return None
    data["age_s"] = int(age)
    return data


def summary():
    """L'état ramené à ce qui tient sur un afficheur.

    On ne liste pas les conteneurs un par un : ce qui compte de loin, c'est
    combien tournent et si l'un d'eux est tombé. Le détail a sa place sur la
    page web, pas sur trente colonnes.
    """
    d = status()
    if d is None:
        return {"ok": False, "up": 0, "total": 0, "down": [],
                "disk_pct": 0, "mem_pct": 0, "uptime": ""}

    containers = d.get("containers") or []
    up = [c for c in containers if c.get("state") == "running"]
    down = [c["name"] for c in containers if c.get("state") != "running"]
    # Un conteneur « running (unhealthy) » tourne mais ne répond pas : le
    # compter comme opérationnel masquerait exactement la panne qu'on cherche.
    sick = [c["name"] for c in up if "unhealthy" in (c.get("status") or "")]

    return {
        "ok": not down and not sick,
        "up": len(up) - len(sick),
        "total": len(containers),
        "down": (down + sick)[:3],
        "disk_pct": d.get("disk_pct", 0),
        "disk_free_gb": d.get("disk_free_gb", 0),
        "mem_pct": d.get("mem_pct", 0),
        "load": d.get("load", 0),
        "uptime": "{}j {}h".format(d.get("uptime_days", 0),
                                   d.get("uptime_hours", 0)),
    }
