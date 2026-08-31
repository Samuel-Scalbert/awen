#!/usr/bin/env bash
# Met à jour Awen sur le serveur depuis GitHub, puis reconstruit le conteneur.
#
# Appelé par awen-update.timer (voir install-updater.sh) ou à la main.
# On interroge GitHub au lieu de recevoir un webhook : le serveur reste
# totalement injoignable depuis Internet. Ouvrir un port sur la box — ou
# monter un tunnel — pour un dépôt qui bouge quelques fois par jour serait
# payer cher une poignée de minutes de latence.
set -euo pipefail

cd "$(dirname "$0")/.."

git fetch --quiet origin main
local_rev=$(git rev-parse HEAD)
remote_rev=$(git rev-parse origin/main)

if [ "$local_rev" = "$remote_rev" ]; then
    exit 0          # rien de neuf : on ne reconstruit pas pour rien
fi

echo "Mise à jour ${local_rev:0:7} -> ${remote_rev:0:7}"

# On fusionne la révision déjà récupérée plus haut, sans rappeler GitHub :
# un second aller-retour réseau, c'est une occasion de plus d'échouer, et la
# garantie de déployer autre chose que la révision qu'on vient de comparer si
# quelqu'un pousse entre-temps.
#
# --ff-only : si un fichier a été modifié directement sur le serveur, la mise
# à jour échoue franchement au lieu de fabriquer un conflit silencieux.
git merge --ff-only "$remote_rev"

# Si la construction échoue, compose laisse le conteneur actuel en place :
# le serveur continue de répondre avec la version précédente.
docker compose up -d --build

# Sans ça, chaque reconstruction laisse une image orpheline sur le disque.
docker image prune -f --filter "dangling=true"

echo "Awen à jour."
