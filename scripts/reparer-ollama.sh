#!/usr/bin/env bash
# Repart de zero sur le magasin de modeles d'Ollama, et VERIFIE.
#
#   ssh awen
#   cd awen && sudo ./scripts/reparer-ollama.sh
#
# POURQUOI IL FAUT EFFACER PLUTOT QUE RETELECHARGER
#
# Un telechargement interrompu laisse des fichiers a la bonne taille et au
# contenu vide. Ollama ne les revalide pas : il voit la taille attendue, en
# conclut que la couche est deja la, et repond « success » en une seconde
# sans rien ecrire. Le disque ne bouge pas d'un octet.
#
# Et la boucle se referme : `ollama rm` doit lire le manifeste pour savoir
# quels fichiers effacer, or c'est justement lui qui est illisible ; le
# ménage automatique, lui, est desactive des qu'un manifeste est corrompu
# (« corrupt manifests detected, skipping prune operation »). Le serveur ne
# peut donc plus sortir de cet etat par ses propres moyens, et une seule
# entree abimee fait echouer TOUS les modeles, meme sains : la requete
# parcourt le magasin et s'arrete sur le premier fichier vide.
#
# CE SCRIPT NE CROIT AUCUNE ANNONCE DE SUCCES
#
# Il mesure l'espace disque avant et apres. Un telechargement de 2,5 Go qui
# ne consomme pas 2,5 Go n'a pas eu lieu, quoi qu'en dise le message.
set -euo pipefail

MODELE="${1:-qwen3:4b}"
STORE=/usr/share/ollama/.ollama/models

if [ "$(id -u)" -ne 0 ]; then
    echo "À lancer avec sudo : sudo $0 [modele]" >&2
    exit 1
fi

etape() { printf '\n\033[36m== %s\033[0m\n' "$*"; }
used_mb() { df --output=used -BM / | tail -1 | tr -dc '0-9'; }

etape "1/5  Arret du service"
systemctl stop ollama
sleep 2

etape "2/5  Suppression du magasin"
du -sh "$STORE" 2>/dev/null || echo "(magasin absent)"
rm -rf "$STORE"
mkdir -p "$STORE"
chown -R ollama:ollama /usr/share/ollama/.ollama

etape "3/5  Redemarrage"
systemctl start ollama
for _ in $(seq 1 40); do
    curl -sf -m 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
    sleep 1
done
curl -s -m 5 http://127.0.0.1:11434/api/version; echo

etape "4/5  Telechargement de $MODELE"
# NE RIEN REDEMARRER APRES CE POINT. Ollama fait le menage des fichiers non
# references a chaque demarrage ; relancer le service pendant ou juste apres
# un telechargement lui fait effacer ce qu'il vient d'ecrire.
avant=$(used_mb)
echo "disque avant : ${avant} Mo"
debut=$(date +%s)
ollama pull "$MODELE"
apres=$(used_mb)
duree=$(( $(date +%s) - debut ))
ecart=$(( apres - avant ))
echo "disque apres : ${apres} Mo   (ecart : ${ecart} Mo en ${duree} s)"

if [ "$ecart" -lt 500 ]; then
    echo
    echo "ECHEC : le disque n'a pas grossi, donc rien n'a ete telecharge."
    echo "Le magasin contient encore des fichiers vides. Relancer ce script."
    exit 1
fi

etape "5/5  Verification par generation"
reponse=$(curl -s -m 300 http://127.0.0.1:11434/api/generate \
    -d "{\"model\":\"$MODELE\",\"prompt\":\"Dis bonjour en une phrase.\",\"stream\":false,\"think\":false}")
python3 - "$reponse" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
if 'error' in d:
    print('ECHEC :', d['error']); raise SystemExit(1)
n = d.get('eval_count') or 0
t = (d.get('eval_duration') or 1) / 1e9
print('reponse :', (d.get('response') or '').strip()[:200])
print('%d tokens | %.1f tokens/s | chargement %.1f s'
      % (n, n / t, (d.get('load_duration') or 0) / 1e9))
PY

nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader
ollama ps
echo
echo "Modele operationnel. Ne pas relancer le service : le menage au"
echo "demarrage effacerait ce qui vient d'etre ecrit si un manifeste"
echo "n'etait pas encore visible."
