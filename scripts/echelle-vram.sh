#!/usr/bin/env bash
# Cherche la plus grosse quantite de VRAM que cette carte accepte de remplir.
#
#   sudo ./scripts/echelle-vram.sh
#
# CE QU'ON A MESURE, ET POURQUOI CE TEST
#
# Le moniteur a filme la coupure du 16/09 a 17:54:41 :
#
#     17:54:40   18 W, 42 °C,   25 Mio de VRAM
#     17:54:41   42 W, 43 °C, 4803 Mio de VRAM
#     ... plus rien, la machine repart 37 s plus tard
#
# Elle est morte a QUARANTE-DEUX WATTS, et pstore etait vide aux deux
# demarrages : ni surconsommation, ni panique du noyau. Au demarrage suivant,
# la carte a tenu dix secondes a 45 W avec les frequences memoire au maximum
# — mais avec 2 Mio de VRAM occupee.
#
# Ce n'est donc pas la puissance qui tue la machine, c'est le REMPLISSAGE DE
# LA VRAM. Brider la carte n'y change rien ; ce qu'il faut connaitre, c'est le
# seuil.
#
# Ce script monte par paliers — 0,6B puis 1,7B puis 4B puis 8B, soit environ
# 0,6, 1,4, 2,5 et 5,2 Gio — et ecrit chaque etape sur le disque AVANT de la
# tenter. Si la machine tombe, la derniere ligne du journal dit quel palier
# l'a tuee : c'est la mesure, et c'est aussi le plus gros modele utilisable.
#
#   cat /var/log/echelle-vram.log
set -uo pipefail

JOURNAL=/var/log/echelle-vram.log
PALIERS=(qwen3:0.6b qwen3:1.7b qwen3:4b qwen3:8b)

[ "$(id -u)" -eq 0 ] || { echo "sudo requis" >&2; exit 1; }

note() {
    printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*" >> "$JOURNAL"
    sync
    printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*"
}

note "===================== nouvelle echelle ====================="

for modele in "${PALIERS[@]}"; do
    note "--- $modele : telechargement ---"
    if ! ollama pull "$modele" >/dev/null 2>&1; then
        note "$modele : telechargement impossible, on passe"
        continue
    fi
    # Le telechargement est ecrit AVANT la manoeuvre qui fait tomber la
    # machine. S'il elle coupe dans dix secondes, ces octets survivent et la
    # prochaine campagne ne les retelechargera pas.
    sync
    note "$modele : telecharge et ecrit sur le disque"

    note "$modele : CHARGEMENT EN VRAM — c'est ici que la machine peut tomber"
    debut=$(date +%s)
    reponse=$(curl -s -m 240 http://127.0.0.1:11434/api/generate \
        -d "{\"model\":\"$modele\",\"prompt\":\"Dis bonjour en une phrase.\",\"stream\":false,\"think\":false}" 2>&1)
    duree=$(( $(date +%s) - debut ))

    if printf '%s' "$reponse" | grep -q '"response"'; then
        vram=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader)
        vitesse=$(printf '%s' "$reponse" | python3 -c "
import json,sys
d=json.load(sys.stdin)
n=d.get('eval_count') or 0
t=(d.get('eval_duration') or 1)/1e9
print('%d tokens, %.1f tokens/s' % (n, n/t))
" 2>/dev/null)
        note "$modele : TENU en ${duree} s | VRAM $vram | $vitesse"
        note "$modele : reponse = $(printf '%s' "$reponse" | python3 -c "
import json,sys; print((json.load(sys.stdin).get('response') or '').strip()[:100])" 2>/dev/null)"
    else
        note "$modele : ECHEC — $(printf '%s' "$reponse" | head -c 150)"
        note "arret de l'echelle : inutile de monter plus haut"
        break
    fi

    # Decharger avant le palier suivant, pour que chaque mesure parte de zero.
    curl -s -m 30 http://127.0.0.1:11434/api/generate \
        -d "{\"model\":\"$modele\",\"keep_alive\":0}" >/dev/null 2>&1
    sleep 8
done

note "===================== echelle terminee ====================="
echo
echo "Journal : $JOURNAL"
echo "Si la machine est tombee, sa derniere ligne nomme le palier fatal."
