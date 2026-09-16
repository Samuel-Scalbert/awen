#!/usr/bin/env bash
# Sollicite la carte graphique par paliers, et ecrit ce qu'elle consomme au
# moment ou la machine tombe.
#
#   sudo ./scripts/test-alim.sh            # paliers 100 -> 220 W
#   sudo ./scripts/test-alim.sh 130        # un seul palier
#
# POURQUOI CE SCRIPT EXISTE
#
# Le serveur se coupe net pendant le chargement d'un modele : le journal
# s'arrete en pleine phrase, sans sequence d'arret, et la machine revient
# trente secondes plus tard. Rien n'est ecrit, donc rien n'explique — c'est
# la signature d'une coupure d'alimentation ou d'une reinitialisation
# materielle, pas d'un plantage logiciel qui, lui, aurait le temps de se
# plaindre.
#
# Le probleme d'un tel defaut, c'est qu'il emporte ses propres traces. Ce
# script ecrit donc chaque releve AVEC UN sync IMMEDIAT : la ligne est sur le
# disque avant la suivante, et le dernier releve survivra a la coupure. On
# saura a quelle puissance la machine a lache.
#
# LE FICHIER A LIRE APRES UN REDEMARRAGE : /var/log/test-alim.log
set -uo pipefail

JOURNAL=/var/log/test-alim.log
MODELE="${MODELE:-qwen3:8b}"

if [ "$(id -u)" -ne 0 ]; then
    echo "À lancer avec sudo : sudo $0 [watts]" >&2
    exit 1
fi

# Chaque ligne est ecrite puis forcee sur le disque. Sans ce sync, le journal
# resterait en cache et disparaitrait avec la coupure qu'on essaie de mesurer.
note() {
    printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*" >> "$JOURNAL"
    sync
    printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*"
}

if [ $# -ge 1 ]; then
    PALIERS=("$1")
else
    PALIERS=(100 130 160 190 220)
fi

note "===== nouvelle campagne, paliers : ${PALIERS[*]} W ====="
note "alimentation declaree : 600 W | carte : $(nvidia-smi --query-gpu=name --format=csv,noheader)"

nvidia-smi -pm 1 >/dev/null 2>&1

for watts in "${PALIERS[@]}"; do
    note "---- palier ${watts} W ----"
    if ! nvidia-smi -pl "$watts" >/dev/null 2>&1; then
        note "palier ${watts} W refuse par le pilote, on passe"
        continue
    fi

    # Le releveur tourne en fond et ecrit une ligne par seconde, sync compris.
    ( while true; do
        printf '%s  %s\n' "$(date '+%H:%M:%S')" \
          "$(nvidia-smi --query-gpu=power.draw,temperature.gpu,utilization.gpu,memory.used \
             --format=csv,noheader 2>/dev/null)" >> "$JOURNAL"
        sync
        sleep 1
      done ) &
    RELEVEUR=$!

    note "chargement du modele $MODELE"
    debut=$(date +%s)
    reponse=$(curl -s -m 240 http://127.0.0.1:11434/api/generate \
        -d "{\"model\":\"$MODELE\",\"prompt\":\"Compte de 1 a 40 en toutes lettres.\",\"stream\":false,\"think\":false}" 2>&1)
    duree=$(( $(date +%s) - debut ))

    kill "$RELEVEUR" 2>/dev/null
    wait "$RELEVEUR" 2>/dev/null

    if printf '%s' "$reponse" | grep -q '"response"'; then
        note "palier ${watts} W : TENU en ${duree} s"
        note "pic de consommation : $(grep -oE '[0-9]+\.[0-9]+ W' "$JOURNAL" | sort -n | tail -1)"
    else
        note "palier ${watts} W : ECHEC — $(printf '%s' "$reponse" | head -c 160)"
    fi
    sleep 5
done

note "===== campagne terminee sans coupure ====="
note "remise a la limite par defaut"
nvidia-smi -pl 220 >/dev/null 2>&1
echo
echo "Journal complet : $JOURNAL"
echo "Apres une coupure, ses dernieres lignes disent a quelle puissance."
