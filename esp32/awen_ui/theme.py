"""Palettes de l'afficheur, en RGB565.

Les couleurs sont converties une fois à l'import : l'ESP32 n'a aucune raison
de refaire ce calcul à chaque image.

Pour changer d'ambiance, une seule ligne à toucher dans app.py :
    from theme import AMBER as PAL      # ou PHOSPHOR, ou ICE
"""


def rgb(r, g, b):
    """RGB 8-8-8 vers RGB565, le format attendu par le ST7789."""
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


class _Palette:
    """Cinq rôles, pas plus.

    Se limiter à cinq couleurs n'est pas une coquetterie : c'est ce qui donne
    à TARS son côté instrument. Dès qu'un écran en utilise sept, il ressemble
    à un tableau de bord d'avion de ligne, plus à un monolithe.
    """

    def __init__(self, bg, fg, dim, hi, alert):
        self.BG = bg        # le fond, presque toujours noir absolu
        self.FG = fg        # l'encre de données
        self.DIM = dim      # étiquettes, unités, ce qui ne se lit pas de loin
        self.HI = hi        # la valeur qui compte sur l'écran
        self.ALERT = alert  # uniquement pour ce qui doit interrompre


AMBER = _Palette(
    bg=rgb(0, 0, 0), fg=rgb(255, 176, 0), dim=rgb(128, 88, 0),
    hi=rgb(255, 232, 180), alert=rgb(255, 64, 32))

PHOSPHOR = _Palette(
    bg=rgb(0, 0, 0), fg=rgb(0, 255, 128), dim=rgb(0, 112, 56),
    hi=rgb(200, 255, 224), alert=rgb(255, 96, 0))

ICE = _Palette(
    bg=rgb(2, 6, 10), fg=rgb(180, 230, 255), dim=rgb(60, 92, 112),
    hi=rgb(255, 255, 255), alert=rgb(255, 96, 96))
