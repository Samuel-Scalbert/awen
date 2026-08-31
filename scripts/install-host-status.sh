#!/usr/bin/env bash
# Installe le relevé d'état de la machine, toutes les minutes.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"
USER_NAME="$(whoami)"

sudo tee /etc/systemd/system/awen-host-status.service >/dev/null <<EOF
[Unit]
Description=Releve l'etat de la machine pour Awen
After=docker.service

[Service]
Type=oneshot
User=${USER_NAME}
WorkingDirectory=${REPO}
ExecStart=${REPO}/scripts/host-status.sh
EOF

sudo tee /etc/systemd/system/awen-host-status.timer >/dev/null <<'EOF'
[Unit]
Description=Releve l'etat de la machine toutes les minutes

[Timer]
OnBootSec=30s
OnUnitActiveSec=1min
# Sans Persistent, un serveur qui dort se reveille avec un etat perime et
# attend la minute suivante pour le rafraichir.
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now awen-host-status.timer
sudo systemctl start awen-host-status.service

echo "Releve installe. Prochain passage :"
systemctl list-timers awen-host-status.timer --no-pager | head -2 | tail -1
echo
echo "Contenu actuel :"
cat "${REPO}/data/host-status.json"
