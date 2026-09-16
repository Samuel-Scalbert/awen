#!/usr/bin/env bash
# Enregistre l'etat de la machine une fois par seconde, sur le disque.
#
# POURQUOI UN SERVICE ET PAS UNE COMMANDE
#
# La panne qu'on cherche coupe la machine sans rien ecrire : pas de sequence
# d'arret, pas de message, le journal s'arrete en pleine phrase. Tout ce qui
# vit dans un terminal SSH meurt avec elle, et tout ce qui reste en cache
# disparait avec le courant.
#
# Ce moniteur est donc lance par systemd des le demarrage, et FORCE CHAQUE
# LIGNE SUR LE DISQUE avant d'ecrire la suivante. Apres une coupure, la
# derniere ligne du fichier decrit la seconde qui a precede la mort.
#
#   sudo ./scripts/moniteur.sh installer     # une fois
#   cat /var/log/awen-moniteur.log           # apres chaque coupure
#
set -uo pipefail

JOURNAL=/var/log/awen-moniteur.log
MAX_LIGNES=200000          # ~55 h a une ligne par seconde

installer() {
    [ "$(id -u)" -eq 0 ] || { echo "sudo requis" >&2; exit 1; }
    install -m 755 "$(readlink -f "$0")" /usr/local/bin/awen-moniteur
    cat > /etc/systemd/system/awen-moniteur.service <<'UNIT'
[Unit]
Description=Moniteur materiel Awen (une ligne par seconde, forcee sur le disque)
After=nvidia-persistenced.service

[Service]
Type=simple
ExecStart=/usr/local/bin/awen-moniteur
Restart=always
RestartSec=2
Nice=-5

[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload
    systemctl enable --now awen-moniteur.service
    sleep 3
    echo "installe. Dernieres lignes :"
    tail -3 "$JOURNAL"
    exit 0
}

[ "${1:-}" = "installer" ] && installer

# --- entete de demarrage : ce qui explique la coupure precedente -----------
{
    echo "================================================================"
    echo "DEMARRAGE $(date '+%F %T')  |  uptime $(cut -d' ' -f1 /proc/uptime)s"
    # pstore garde les paniques du noyau a travers un redemarrage quand le
    # BIOS le permet. Un fichier ici = plantage logiciel. Rien = coupure de
    # courant : une panique a le temps d'ecrire, pas une coupure.
    if ls /sys/fs/pstore/* >/dev/null 2>&1; then
        echo "PSTORE : PANIQUE NOYAU ENREGISTREE -> $(ls /sys/fs/pstore/)"
    else
        echo "PSTORE : vide (coupure d'alimentation, pas de panique logicielle)"
    fi
    echo "GPU    : $(nvidia-smi --query-gpu=name,power.limit --format=csv,noheader 2>&1)"
    echo "RAM    : $(free -m | awk '/^Mem:/{print $2" Mo"}')"
    echo "colonnes : heure | W | °GPU | %GPU | MiB | MHz | °CPU | charge | RAM libre"
    echo "================================================================"
} >> "$JOURNAL"
sync

cpu_temp() {
    for z in /sys/class/hwmon/hwmon*/temp1_input; do
        [ -r "$z" ] || continue
        n=$(cat "$(dirname "$z")/name" 2>/dev/null)
        if [ "$n" = "k10temp" ]; then
            awk '{printf "%.0f", $1/1000}' "$z"; return
        fi
    done
    echo "--"
}

while true; do
    gpu=$(nvidia-smi --query-gpu=power.draw,temperature.gpu,utilization.gpu,memory.used,clocks.sm \
          --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')
    [ -n "$gpu" ] || gpu="--,--,--,--,--"
    printf '%s %s %s %s %s\n' \
        "$(date '+%H:%M:%S')" "$gpu" "$(cpu_temp)" \
        "$(cut -d' ' -f1 /proc/loadavg)" \
        "$(free -m | awk '/^Mem:/{print $7}')" >> "$JOURNAL"
    # Le sync est tout l'interet du moniteur : sans lui, les dernieres
    # secondes — les seules qui nous interessent — resteraient en cache et
    # partiraient avec le courant.
    sync
    # Le fichier ne doit pas remplir le disque au fil des semaines.
    if [ "$(( $(date +%s) % 3600 ))" -lt 2 ]; then
        lignes=$(wc -l < "$JOURNAL")
        if [ "$lignes" -gt "$MAX_LIGNES" ]; then
            tail -n $((MAX_LIGNES / 2)) "$JOURNAL" > "$JOURNAL.tmp"
            mv "$JOURNAL.tmp" "$JOURNAL"
            sync
        fi
    fi
    sleep 1
done
