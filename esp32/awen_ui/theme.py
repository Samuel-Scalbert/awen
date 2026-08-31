"""Palettes de l'afficheur, en RGB565, et leur persistance.

Les couleurs sont converties une fois à l'import : l'ESP32 n'a aucune raison
de refaire ce calcul à chaque image.

Chaque palette tient en cinq rôles, pas plus. Se limiter à cinq n'est pas une
coquetterie : c'est ce qui donne à l'écran son allure d'instrument. Dès qu'un
écran en utilise sept, il ressemble à un tableau de bord d'avion de ligne.

Le choix est enregistré dans un fichier sur la carte, pour survivre à une
coupure de courant.
"""

_STORE = "awen_theme.txt"


def rgb(r, g, b):
    """RGB 8-8-8 vers RGB565, le format attendu par le ST7789."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


class Palette:
    def __init__(self, name, bg, fg, dim, hi, alert):
        self.name = name
        self.BG = bg        # le fond, presque toujours noir absolu
        self.FG = fg        # l'encre de données
        self.DIM = dim      # étiquettes, unités, ce qui ne se lit pas de loin
        self.HI = hi        # la valeur qui compte sur l'écran
        self.ALERT = alert  # uniquement pour ce qui doit interrompre


# Le noir absolu fait le contraste, pas la luminosité du texte : c'est ce qui
# distingue un instrument d'un écran d'ordinateur. DIM est toujours la teinte
# principale assombrie, jamais un gris — un gris casserait l'unité de la
# palette et donnerait l'air d'une erreur d'affichage.
AMBER = Palette("AMBRE",
                rgb(0, 0, 0), rgb(255, 176, 0), rgb(128, 88, 0),
                rgb(255, 232, 180), rgb(255, 64, 32))

PHOSPHOR = Palette("VERT",
                   rgb(0, 0, 0), rgb(0, 255, 128), rgb(0, 112, 56),
                   rgb(200, 255, 224), rgb(255, 96, 0))

ICE = Palette("BLEU",
              rgb(2, 6, 10), rgb(120, 200, 255), rgb(40, 78, 104),
              rgb(230, 245, 255), rgb(255, 96, 96))

VIOLET = Palette("VIOLET",
                 rgb(4, 0, 8), rgb(198, 130, 255), rgb(88, 52, 120),
                 rgb(238, 220, 255), rgb(255, 96, 128))

RUBIS = Palette("RUBIS",
                rgb(6, 0, 0), rgb(255, 96, 96), rgb(120, 40, 40),
                rgb(255, 214, 214), rgb(255, 176, 0))

PAPIER = Palette("PAPIER",
                 rgb(0, 0, 0), rgb(226, 226, 222), rgb(104, 106, 104),
                 rgb(255, 255, 255), rgb(255, 96, 64))

# L'ordre du sélecteur. L'ambre en tête : c'est la teinte de TARS.
PALETTES = (AMBER, PHOSPHOR, ICE, VIOLET, RUBIS, PAPIER)

DEFAULT = AMBER


def by_name(name):
    for p in PALETTES:
        if p.name == name:
            return p
    return DEFAULT


def load():
    """La palette enregistrée, ou l'ambre si rien n'a jamais été choisi.

    Un fichier absent est le cas normal au premier démarrage, pas une erreur :
    on retombe silencieusement sur la valeur par défaut.
    """
    try:
        with open(_STORE) as f:
            return by_name(f.read().strip())
    except OSError:
        return DEFAULT


def save(palette):
    """Enregistre le choix. Un échec d'écriture ne doit pas tuer l'affichage.

    Si la mémoire est pleine ou en lecture seule, on préfère un thème qui ne
    survit pas au redémarrage plutôt qu'une carte qui ne démarre plus.
    """
    try:
        with open(_STORE, "w") as f:
            f.write(palette.name)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# Couleur d'identite des ecrans
#
# Elles ne dependent PAS de la palette choisie : c'est un reperage, pas une
# decoration. Si le theme change, l'ecran Spotify reste vert — sinon la LED
# et les pastilles cesseraient de vouloir dire quelque chose.
#
# En RVB 0-255 pour la LED ; grid.dots() les convertit lui-meme pour l'ecran.

SCREEN_RGB = (
    (255, 120, 0),      # accueil    orange
    (0, 110, 255),      # seance     bleu
    (0, 220, 90),       # spotify    vert
    (255, 40, 40),      # coach      rouge
    (190, 90, 255),     # jobs       violet
    (0, 210, 220),      # parametres cyan
    (240, 240, 240),    # theme      blanc
)


def rgb565(c):
    """Triplet 0-255 vers RGB565, pour l'affichage des pastilles."""
    return rgb(c[0], c[1], c[2])
