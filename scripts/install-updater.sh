#!/usr/bin/env bash
# Installe la mise à jour automatique d'Awen (à lancer une seule fois).
#
#   ./scripts/install-updater.sh
#
# Crée un service systemd qui exécute deploy.sh toutes les 5 minutes. Les
# chemins et l'utilisateur sont déduits d'ici, pour ne rien coder en dur dans
# le dépôt.
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_AS="$(id -un)"

if ! id -nG "$RUN_AS" | tr ' ' '\n' | grep -qx docker; then
    echo "⚠  $RUN_AS n'est pas dans le groupe docker : le service ne pourra pas"
    echo "   reconstruire le conteneur. Corrige avec :"
    echo "     sudo usermod -aG docker $RUN_AS && newgrp docker"
    exit 1
fi

sudo tee /etc/systemd/system/awen-update.service > /dev/null <<EOF
[Unit]
Description=Mise a jour d'Awen depuis GitHub
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
User=$RUN_AS
WorkingDirectory=$DIR
ExecStart=$DIR/scripts/deploy.sh
EOF

sudo tee /etc/systemd/system/awen-update.timer > /dev/null <<'EOF'
[Unit]
Description=Verifie les mises a jour d'Awen toutes les 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
# Evite de taper GitHub pile a la meme seconde a chaque cycle.
RandomizedDelaySec=30
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now awen-update.timer

echo
echo "Mise a jour automatique active pour $DIR (utilisateur $RUN_AS)."
echo "  Prochain passage : systemctl list-timers awen-update.timer"
echo "  Journal          : journalctl -u awen-update.service -f"
echo "  Deploiement      : ./scripts/deploy.sh"
