"""Les couleurs de l'afficheur, en RGB565.

Elles sont converties une fois à l'import : l'ESP32 n'a aucune raison de
refaire ce calcul à chaque image.

UNE SEULE PALETTE, CELLE DES MAQUETTES

Les trois pages ont été dessinées dans une teinte, l'ambre, et chaque
couleur y a un rôle. Les six palettes au choix des sept écrans sont parties
avec l'écran Thème : une teinte qu'on n'a jamais vue sur ces pages ne peut
pas être promise lisible. En rajouter une, c'est écrire une seconde
Palette ici et la regarder dans le simulateur avant de la proposer.

Neuf rôles, pas plus. Le noir absolu fait le contraste, pas la luminosité
du texte : c'est ce qui distingue un instrument d'un écran d'ordinateur.
"""


def rgb(r, g, b):
    """RGB 8-8-8 vers RGB565, le format attendu par le ST7789."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


class Palette:
    def __init__(self, name, bg, fg, hi, dim, alert, ghost, rule, faint, past):
        self.name = name
        self.BG = bg        # le fond, noir absolu
        self.FG = fg        # l'accent : l'heure, ce qui est en cours
        self.HI = hi        # l'encre des valeurs et des titres
        self.DIM = dim      # libellés, unités, ce qui situe sans se lire
        self.ALERT = alert  # uniquement pour ce qui doit interrompre
        self.GHOST = ghost  # les segments éteints de l'horloge
        self.RULE = rule    # filets et rails de jauge
        self.FAINT = faint  # repères inactifs, tout juste visibles
        self.PAST = past    # ce qui est déjà passé dans la journée


AMBER = Palette("AMBRE",
                rgb(0, 0, 0), rgb(255, 176, 0), rgb(242, 232, 208),
                rgb(143, 134, 114), rgb(255, 91, 69), rgb(28, 21, 0),
                rgb(42, 36, 24), rgb(74, 62, 34), rgb(106, 98, 80))

DEFAULT = AMBER


def load():
    return DEFAULT


# LE LOGO GARDE SES COULEURS
#
# C'est la seule entorse à la palette, et elle est assumée : c'est le même
# objet que le 🌀 du site, avec son bleu-violet.
#
# Huit teintes en dégradé, du violet clair au bleu de nuit. Chaque image du
# logo indexe cet anneau : la traînée tourne sans qu'on recalcule quoi que
# ce soit, et une comète dit « ça tourne » là où huit points identiques ne
# diraient rien.
LOGO_RING = (
    rgb(190, 150, 255), rgb(160, 125, 240), rgb(130, 105, 225),
    rgb(100, 85, 210), rgb(75, 70, 190), rgb(55, 55, 165),
    rgb(40, 42, 135), rgb(28, 32, 105),
)

# La couleur de la LED, page par page : on sait où l'on est sans lire.
# En RVB 0-255, tel que la LED les attend.
SCREEN_RGB = (
    (255, 120, 0),      # accueil     orange
    (0, 220, 90),       # spotify     vert
    (0, 110, 255),      # calendrier  bleu
)
