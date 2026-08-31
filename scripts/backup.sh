#!/usr/bin/env bash
# Sauvegarde la base d'Awen et ne conserve que les 7 dernières.
#
# Utilise « sqlite3 .backup » et non un cp : la commande produit une copie
# cohérente même si l'application écrit pendant ce temps, alors qu'un cp
# pris au mauvais moment donne un fichier corrompu.
set -euo pipefail

cd "$(dirname "$0")/.."
DEST="data/backups"
KEEP=7

if ! command -v sqlite3 > /dev/null; then
    echo "sqlite3 absent : sudo apt install -y sqlite3" >&2
    exit 1
fi
if [ ! -f data/awen.db ]; then
    echo "Pas de base à sauvegarder (data/awen.db introuvable)." >&2
    exit 1
fi

mkdir -p "$DEST"
target="$DEST/awen-$(date +%F-%H%M).db"
sqlite3 data/awen.db ".backup '$target'"

# Rotation : on garde les KEEP plus récentes, on supprime le reste.
ls -1t "$DEST"/awen-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --

echo "Sauvegarde : $target ($(ls -1 "$DEST"/awen-*.db | wc -l) conservées)"
