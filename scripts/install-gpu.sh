#!/usr/bin/env bash
# Réveille la RTX 3070 du serveur : pilote propriétaire NVIDIA, puis Ollama.
#
# POURQUOI CE SCRIPT EXISTE
#
# Le serveur démarre avec nouveau, le pilote libre, qui affiche une console
# mais n'expose aucun CUDA. Sans pilote propriétaire, un modèle de langage
# tourne sur le processeur à quelques mots par seconde — techniquement
# « ça marche », pratiquement inutilisable.
#
# Tout ici demande les droits root, et sudo réclame un mot de passe sur cette
# machine : le script doit donc être lancé à la main, il ne peut pas l'être à
# distance sans interaction.
#
#   ssh awen
#   cd awen && sudo ./scripts/install-gpu.sh
#
# Vérifié le 16/09/2026 : la machine démarre en BIOS legacy, donc SANS Secure
# Boot. C'est la bonne nouvelle — le piège habituel (module non signé refusé
# au chargement, avec un message qui parle de pilote introuvable) ne peut pas
# se produire ici.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "À lancer avec sudo : sudo $0" >&2
    exit 1
fi

etape() { printf '\n\033[36m== %s\033[0m\n' "$*"; }

etape "1/5  Dépôts contrib et non-free"
# Le pilote NVIDIA n'est pas libre : il vit dans non-free, absent par défaut
# d'une installation Debian. On ajoute contrib avec, dont dépendent les
# paquets DKMS.
SRC=/etc/apt/sources.list
cp "$SRC" "$SRC.avant-nvidia"
sed -i -E 's/^(deb(-src)? .*trixie(-updates|-security)? main)( non-free-firmware)?$/\1 contrib non-free non-free-firmware/' "$SRC"
grep -E '^deb ' "$SRC"

etape "2/5  Mise à jour de l'index"
apt-get update

etape "3/5  En-têtes du noyau"
# DKMS recompile le module à chaque noyau : sans les en-têtes, l'installation
# du pilote se termine « avec succès » mais ne produit aucun module, et
# nvidia-smi reste introuvable après le redémarrage.
apt-get install -y "linux-headers-$(uname -r)" build-essential dkms

etape "4/5  Pilote NVIDIA"
# Le paquet met nouveau sur liste noire tout seul ; ne pas le faire à la main.
DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-driver firmware-misc-nonfree

etape "5/5  Ollama"
# Le script officiel détecte la carte et installe le service systemd. Il ne
# touche pas au pilote : il faut donc que l'étape 4 ait réussi.
if command -v ollama >/dev/null 2>&1; then
    echo "Ollama est déjà là, on passe."
else
    curl -fsSL https://ollama.com/install.sh | sh
fi

cat <<'FIN'

──────────────────────────────────────────────────────────────────────
  Installé. Il faut maintenant REDÉMARRER pour charger le module.

      sudo reboot

  Awen et le site de films seront coupés une minute ou deux, puis
  remonteront seuls (les conteneurs sont en restart automatique).

  Au retour, vérifier dans cet ordre :

      nvidia-smi                     # doit afficher la 3070 et ses 8 Go
      ollama --version
      ollama pull qwen3:8b           # ~5 Go de téléchargement
      ollama run qwen3:8b "Bonjour, réponds en une phrase."

  Pendant la réponse, dans un second terminal :

      nvidia-smi                     # la VRAM doit être occupée

  Si la VRAM reste à zéro et que la réponse arrive lentement, tout
  tourne sur le processeur : le pilote n'est pas chargé. Regarder

      dmesg | grep -i nvidia
      lsmod | grep -E 'nvidia|nouveau'

  nouveau ne doit plus apparaître.
──────────────────────────────────────────────────────────────────────
FIN
