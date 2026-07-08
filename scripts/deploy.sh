#!/usr/bin/env bash
# Auto-update Awen sur le serveur (PC gamer) à chaque push.
# À appeler via un webhook Git ou un cron/systemd timer.
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
source venv/bin/activate 2>/dev/null || true
pip install -q -r requirements.txt
# Redémarre le service (adapter selon systemd / pm2 / screen)
sudo systemctl restart awen || echo "Configure un service 'awen' pour le redémarrage auto."
