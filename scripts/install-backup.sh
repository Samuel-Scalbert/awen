#!/usr/bin/env bash
# Installe la sauvegarde automatique quotidienne (à lancer une seule fois).
#
#   ./scripts/install-backup.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_AS="$(id -un)"

command -v sqlite3 > /dev/null || sudo apt install -y sqlite3

sudo tee /etc/systemd/system/awen-backup.service > /dev/null <<EOF
[Unit]
Description=Sauvegarde de la base Awen

[Service]
Type=oneshot
User=$RUN_AS
WorkingDirectory=$DIR
ExecStart=$DIR/scripts/backup.sh
EOF

sudo tee /etc/systemd/system/awen-backup.timer > /dev/null <<'EOF'
[Unit]
Description=Sauvegarde quotidienne de la base Awen

[Timer]
OnCalendar=*-*-* 04:00:00
# Le serveur peut etre eteint a 4h : Persistent rattrape la sauvegarde
# manquee au demarrage suivant plutot que de sauter le jour.
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now awen-backup.timer
"$DIR/scripts/backup.sh"

echo
echo "Sauvegarde quotidienne activee (7 dernieres conservees)."
echo "  Prochain passage : systemctl list-timers awen-backup.timer"
echo "  Sauvegardes      : ls -lt $DIR/data/backups/"
echo "  Restaurer        : docker compose down && cp data/backups/<fichier> data/awen.db && docker compose up -d"
