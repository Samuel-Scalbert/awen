#!/usr/bin/env bash
# Installe le bilan du dimanche (à lancer une seule fois, sur le serveur).
#
#   ./scripts/install-coach-hebdo.sh
#
# Chaque dimanche à 20 h, le timer demande au conteneur d'écrire le bilan de
# la semaine : `flask --app run coach-hebdo` (app/services/coach_hebdo.py).
# Claude Code tourne avec l'abonnement, comme pour les lettres : il lui faut
# CLAUDE_CODE_OAUTH_TOKEN dans le .env. Sans lui, le bilan se replie sur les
# observations du coach à règles.
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_AS="$(id -un)"

sudo tee /etc/systemd/system/awen-coach-hebdo.service > /dev/null <<EOF
[Unit]
Description=Bilan du dimanche d'Awen
After=docker.service
Wants=docker.service

[Service]
Type=oneshot
User=$RUN_AS
WorkingDirectory=$DIR
# Au démarrage (rattrapage d'un dimanche manqué), le conteneur peut ne pas
# encore tourner : on l'attend jusqu'à cinq minutes.
ExecStartPre=/bin/sh -c 'for i in \$(seq 60); do [ "\$(docker inspect -f {{.State.Running}} awen 2>/dev/null)" = true ] && exit 0; sleep 5; done; exit 1'
ExecStart=/usr/bin/docker exec awen flask --app run coach-hebdo
# Claude Code met une à trois minutes ; au-delà de quinze, il est bloqué.
TimeoutStartSec=15min
EOF

sudo tee /etc/systemd/system/awen-coach-hebdo.timer > /dev/null <<'EOF'
[Unit]
Description=Bilan du dimanche d'Awen, chaque dimanche à 20 h

[Timer]
OnCalendar=Sun *-*-* 20:00:00
# Serveur éteint dimanche soir : le bilan s'écrit au démarrage suivant, sur
# la semaine qui vient de finir (voir coach_hebdo.semaine_relue).
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now awen-coach-hebdo.timer

echo
echo "Bilan du dimanche activé."
echo "  Prochain passage : systemctl list-timers awen-coach-hebdo.timer"
echo "  Le lancer maintenant : sudo systemctl start awen-coach-hebdo.service"
echo "  Ce qu'il a dit       : journalctl -u awen-coach-hebdo.service -n 20"
