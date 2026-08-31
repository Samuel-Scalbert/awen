#!/usr/bin/env bash
# Écrit l'état de la machine dans data/host-status.json, que l'app lit.
#
# POURQUOI PASSER PAR UN FICHIER
#
# L'autre solution serait de monter /var/run/docker.sock dans le conteneur
# pour qu'Awen interroge Docker directement. Ce socket donne le contrôle
# total du démon : créer un conteneur privilégié, monter le disque hôte, en
# sortir root. Une application web qui affiche la météo n'a pas besoin de ce
# pouvoir, et le lui donner pour une ligne d'état serait disproportionné.
#
# Ce script tourne donc sur l'hôte, en lecture seule, et dépose son résultat
# dans le dossier data/ déjà monté. Awen lit un fichier, rien de plus.
set -euo pipefail

cd "$(dirname "$0")/.."
OUT="data/host-status.json"
TMP="$OUT.tmp"

# Conteneurs : nom, état, santé. `docker ps` seul omet ceux qui sont arrêtés,
# or un conteneur arrêté est précisément ce qu'on veut voir signalé.
containers=$(docker ps -a \
    --format '{"name":"{{.Names}}","state":"{{.State}}","status":"{{.Status}}"}' \
    2>/dev/null | paste -sd, - || true)

disk_pct=$(df --output=pcent / | tail -1 | tr -dc '0-9')
disk_free=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
mem_pct=$(free | awk '/^Mem:/ {printf "%d", $3/$2*100}')
load=$(cut -d' ' -f1 /proc/loadavg)
up_days=$(awk '{printf "%d", $1/86400}' /proc/uptime)
up_hours=$(awk '{printf "%d", ($1%86400)/3600}' /proc/uptime)

# Écriture atomique : l'app peut lire à n'importe quel instant, et un fichier
# à moitié écrit produirait une erreur de parsing plutôt qu'une donnée périmée.
cat > "$TMP" <<EOF
{
  "at": $(date +%s),
  "containers": [${containers}],
  "disk_pct": ${disk_pct},
  "disk_free_gb": ${disk_free},
  "mem_pct": ${mem_pct},
  "load": ${load},
  "uptime_days": ${up_days},
  "uptime_hours": ${up_hours}
}
EOF
mv "$TMP" "$OUT"
