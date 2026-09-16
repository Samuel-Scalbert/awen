#!/usr/bin/env bash
# Rend Ollama joignable depuis le conteneur Awen.
#
#   sudo ./scripts/ollama-reseau.sh
#
# LE PROBLEME
#
# Par defaut, Ollama n'ecoute que sur 127.0.0.1. C'est le bon reglage pour un
# poste de travail, mais le conteneur Awen n'est pas sur cette interface : il
# joint l'hote par le pont Docker, 172.17.0.1, et se fait refuser.
#
#     docker exec awen ... -> host.docker.internal (172.17.0.1) : refuse
#
# CE QU'ON CHANGE, ET CE QUE CA EXPOSE
#
# On demande a Ollama d'ecouter sur toutes les interfaces. Il devient donc
# joignable depuis le reseau local et depuis le tailnet — pas depuis
# Internet, la box ne redirige aucun port. Sur un serveur domestique c'est
# l'usage courant ; pour restreindre davantage, remplacer 0.0.0.0 par
# 172.17.0.1, au prix de casser le client `ollama` de l'hote, qui vise
# 127.0.0.1.
#
# Le fichier est un « drop-in » : il complete l'unite officielle sans la
# modifier, et survit donc aux mises a jour d'Ollama.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "sudo requis" >&2; exit 1; }

CONF=/etc/systemd/system/ollama.service.d/reseau.conf
mkdir -p "$(dirname "$CONF")"
cat > "$CONF" <<'UNIT'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
UNIT

systemctl daemon-reload
systemctl restart ollama

for _ in $(seq 1 30); do
    ss -ltn 2>/dev/null | grep -q '0.0.0.0:11434' && break
    sleep 1
done

echo "== ecoute =="
ss -ltnp 2>/dev/null | grep 11434 || echo "(rien sur 11434)"

echo "== depuis le conteneur Awen =="
docker exec awen python -c "
import urllib.request, json
url = 'http://host.docker.internal:11434/api/tags'
try:
    with urllib.request.urlopen(url, timeout=5) as r:
        noms = [m['name'] for m in json.load(r).get('models', [])]
    print('JOIGNABLE — modeles :', ', '.join(noms) or '(aucun)')
except Exception as e:
    print('INJOIGNABLE :', type(e).__name__, e)
" 2>&1

echo "== ce qu'Awen en dit =="
curl -s http://127.0.0.1:5000/jarvis/etat | python3 -c "
import json, sys
print(json.load(sys.stdin)['ollama'])
"
