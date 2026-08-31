#!/usr/bin/env python3
"""Génère des maquettes de l'écran ESP32 d'Awen, façon TARS (Interstellar).

Pourquoi un script plutôt que des images dessinées à la main : l'écran fait
240x320 et la police embarquée est une bitmap 8x16, soit une grille de 30
colonnes sur 20 lignes. Tout ce qui est composé hors de cette grille est
infaisable sur la vraie machine. Le script impose donc la grille, et ce qui
sort d'ici est directement transposable en MicroPython.

Chaque caractère est positionné à la main sur la grille (col*CW) au lieu de
laisser Pillow gérer le crénage : c'est exactement ce que fera l'ESP32, et
ça évite des maquettes plus flatteuses que le résultat réel.

    python esp32/mockups.py                      # tout, en ambre
    python esp32/mockups.py --palette all
    python esp32/mockups.py --scale 4 --out /tmp/maquettes
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 240, 320
CW, CH = 8, 16          # police 8x16 -> 30 colonnes x 20 lignes
COLS, ROWS = W // CW, H // CH

FONT_PATH = r"C:\Windows\Fonts\consola.ttf"
FONT_BOLD = r"C:\Windows\Fonts\consolab.ttf"

# Trois ambiances. TARS a l'ecran, c'est de l'ambre chaud sur noir absolu :
# le contraste vient du noir d'un ecran eteint, pas de la luminosite du texte.
PALETTES = {
    "amber":    {"bg": (0, 0, 0), "fg": (255, 176, 0), "dim": (128, 88, 0),
                 "hi": (255, 232, 180), "alert": (255, 64, 32)},
    "phosphor": {"bg": (0, 0, 0), "fg": (0, 255, 128), "dim": (0, 112, 56),
                 "hi": (200, 255, 224), "alert": (255, 96, 0)},
    "ice":      {"bg": (2, 6, 10), "fg": (180, 230, 255), "dim": (60, 92, 112),
                 "hi": (255, 255, 255), "alert": (255, 96, 96)},
}

# L'ESP32 dessine des blocs, pas des degrades : on s'interdit tout ce que la
# machine ne sait pas faire vite.
BLOCK, HALF = "\u2588", "\u2591"


class Screen:
    """Un ecran 240x320 compose sur la grille 30x20."""

    def __init__(self, pal):
        self.p = pal
        self.img = Image.new("RGB", (W, H), pal["bg"])
        self.d = ImageDraw.Draw(self.img)
        self.font = ImageFont.truetype(FONT_PATH, 14)
        self.bold = ImageFont.truetype(FONT_BOLD, 14)

    def text(self, col, row, s, color="fg", bold=False):
        """Ecrit sur la grille, un caractere par cellule."""
        f = self.bold if bold else self.font
        c = self.p[color] if isinstance(color, str) else color
        for i, ch in enumerate(s):
            if 0 <= col + i < COLS:
                self.d.text(((col + i) * CW, row * CH + 1), ch, font=f, fill=c)

    def right(self, row, s, color="fg", bold=False):
        self.text(COLS - len(s), row, s, color, bold)

    def center(self, row, s, color="fg", bold=False):
        self.text((COLS - len(s)) // 2, row, s, color, bold)

    def rule(self, row, color="dim", char="\u2500"):
        self.text(0, row, char * COLS, color)

    def bar(self, col, row, width, pct, color="fg"):
        """Jauge en blocs pleins/vides : pas de degrade, l'ESP32 n'en veut pas."""
        filled = round(width * pct / 100)
        self.text(col, row, BLOCK * filled, color)
        self.text(col + filled, row, HALF * (width - filled), "dim")

    def frame(self, col, row, width, height, color="dim"):
        self.text(col, row, "\u250c" + "\u2500" * (width - 2) + "\u2510", color)
        for r in range(row + 1, row + height - 1):
            self.text(col, r, "\u2502", color)
            self.text(col + width - 1, r, "\u2502", color)
        self.text(col, row + height - 1,
                  "\u2514" + "\u2500" * (width - 2) + "\u2518", color)

    def cursor(self, col, row, color="hi"):
        self.d.rectangle([col * CW, row * CH + 2,
                          col * CW + CW - 1, row * CH + CH - 1],
                         fill=self.p[color])

    def header(self, title, clock="21:47"):
        self.text(0, 0, title, "hi", bold=True)
        self.right(0, clock, "dim")
        self.rule(1)

    def statusbar(self, left, right_txt, color="dim"):
        self.rule(ROWS - 2)
        self.text(0, ROWS - 1, left, color)
        self.right(ROWS - 1, right_txt, color)


# --------------------------------------------------------------------------
# Les ecrans. Texte sans accents : une police bitmap 8x16 embarquee n'a
# generalement que l'ASCII, et un « e accent aigu » y sort en carre vide.
# --------------------------------------------------------------------------

def s_boot(p):
    """Sequence d'amorcage : le texte tombe ligne par ligne, comme TARS."""
    s = Screen(p)
    s.center(2, "A W E N", "hi", bold=True)
    s.center(3, "assistant personnel", "dim")
    s.rule(5)
    lines = [
        ("RESEAU", "OK"), ("SERVEUR", "OK"), ("COACH", "OK"),
        ("VEILLE EMPLOI", "OK"), ("CAPTEURS", "..."),
    ]
    for i, (label, state) in enumerate(lines):
        r = 7 + i
        s.text(1, r, label, "dim")
        col = "fg" if state == "OK" else "dim"
        s.text(COLS - 1 - len(state), r, state, col)
    s.text(1, 13, "> demarrage", "fg")
    s.cursor(13, 13)
    s.statusbar("v2.4", "192.168.1.32")
    return s


def s_home(p):
    """Ecran de veille : l'heure domine, le reste chuchote."""
    s = Screen(p)
    s.text(0, 0, "LUN 31 AOU", "dim")
    s.right(0, "\u2588 EN LIGNE", "fg")
    s.rule(1)

    big = ImageFont.truetype(FONT_BOLD, 62)
    s.d.text((W // 2, 74), "21:47", font=big, fill=p["hi"], anchor="mm")

    s.rule(7)
    s.text(1, 9, "PROCHAINE SEANCE", "dim")
    s.text(1, 10, "PULL", "hi", bold=True)
    s.right(10, "dans 11 h", "fg")

    s.text(1, 12, "OFFRES DU JOUR", "dim")
    s.right(12, "3", "hi", bold=True)

    s.text(1, 14, "SERIE EN COURS", "dim")
    s.right(14, "8 seances", "fg")

    s.statusbar("AWEN", "\u2588\u2588\u2588\u2591\u2591 64%")
    return s


def s_gym(p):
    """Seance en cours : une seule information compte, la serie a faire."""
    s = Screen(p)
    s.header("PULL \u00b7 SEANCE 09", "21:47")

    s.text(1, 3, "TIRAGE VERTICAL", "hi", bold=True)
    s.text(1, 4, "exercice 2 / 6", "dim")

    s.frame(0, 6, COLS, 5)
    s.text(2, 7, "SERIE 3 / 4", "dim")
    s.text(2, 8, "40.0 KG", "hi", bold=True)
    s.right(8, "x 10  ")
    s.text(2, 9, "cible 8-12 reps", "dim")

    s.text(1, 12, "REPOS", "dim")
    s.text(1, 13, "00:47", "hi", bold=True)
    s.bar(8, 13, 20, 78)

    s.text(1, 15, "FAIT", "dim")
    s.bar(8, 15, 20, 45)
    s.right(16, "9 series restantes", "dim")

    s.statusbar("< PREC", "SUIV >")
    return s


def s_coach(p):
    """Le conseil du moteur de regles, avec le ton sec de TARS."""
    s = Screen(p)
    s.header("COACH", "21:47")

    s.text(1, 3, "! CHARGE INADAPTEE", "alert", bold=True)
    s.text(1, 5, "EXTENSION TRICEPS", "hi")
    s.text(1, 6, "POULIE", "hi")

    s.text(1, 8, "36% des series dans", "dim")
    s.text(1, 9, "la cible 8-12 reps", "dim")

    s.rule(11)
    s.text(1, 12, "PROPOSITION", "dim")
    s.text(1, 13, "22.5 KG", "hi", bold=True)
    s.text(9, 13, "->", "dim")
    s.text(12, 13, "20.0 KG", "fg", bold=True)

    s.text(1, 15, "confiance", "dim")
    s.bar(12, 15, 16, 90)

    s.statusbar("[A] APPLIQUER", "[B] IGNORER")
    return s


def s_settings(p):
    """L'ecran iconique de TARS : des reglages en pourcentage, assumes."""
    s = Screen(p)
    s.header("PARAMETRES", "21:47")

    params = [
        ("SINCERITE", 95), ("HUMOUR", 75),
        ("INSISTANCE", 60), ("VERBOSITE", 40),
    ]
    for i, (name, val) in enumerate(params):
        r = 4 + i * 3
        s.text(1, r, name, "hi" if i == 0 else "fg")
        s.right(r, "{:>3}%".format(val), "hi", bold=True)
        s.bar(1, r + 1, 28, val)

    s.text(1, 17, "> reglage HUMOUR", "dim")
    s.cursor(18, 17)
    s.statusbar("^v AJUSTER", "[OK] VALIDER")
    return s


def s_jobs(p):
    """Veille emploi : trois titres, pas plus. 30 colonnes, il faut trancher."""
    s = Screen(p)
    s.header("VEILLE EMPLOI", "21:47")

    s.text(1, 3, "3", "hi", bold=True)
    s.text(3, 3, "OFFRES CE MATIN", "fg")

    offers = [
        ("DATA ENGINEER", "Sancare", 92),
        ("PRODUCT OWNER DATA", "AXA Direct", 78),
        ("BUSINESS ANALYST", "Adone Conseil", 64),
    ]
    for i, (title, org, score) in enumerate(offers):
        r = 5 + i * 4
        s.text(0, r, ">", "dim")
        s.text(2, r, title[:26], "hi")
        s.text(2, r + 1, org, "dim")
        s.right(r + 1, "{}%".format(score), "fg")
        s.bar(2, r + 2, 26, score)

    s.statusbar("PIPELINE 09:00", "v DEFILER")
    return s


def s_chat(p):
    """La discussion, pour le jour ou Awen parlera. Le texte s'ecrit."""
    s = Screen(p)
    s.header("> AWEN", "21:47")

    s.text(0, 3, "VOUS", "dim")
    s.text(0, 4, "combien je souleve au", "fg")
    s.text(0, 5, "developpe couche ?", "fg")

    s.text(0, 7, "AWEN", "hi", bold=True)
    for i, line in enumerate([
        "42.5 kg sur ta derniere",
        "seance, quatre series",
        "de dix. Tu as pris cinq",
        "kilos en six semaines.",
    ]):
        s.text(0, 8 + i, line, "fg")
    s.text(0, 12, "Continue comme ca.", "fg")
    s.cursor(19, 12)

    s.statusbar("* ECOUTE", "8B LOCAL")
    return s


SCREENS = {
    "01-boot": s_boot, "02-home": s_home, "03-gym": s_gym,
    "04-coach": s_coach, "05-settings": s_settings,
    "06-jobs": s_jobs, "07-chat": s_chat,
}


def contact_sheet(images, cols=4, gap=40, bg=(18, 18, 18)):
    """Planche de contact : voir les ecrans cote a cote, comme sur un bureau."""
    rows = (len(images) + cols - 1) // cols
    w, h = images[0].size
    sheet = Image.new("RGB", (cols * w + gap * (cols + 1),
                              rows * h + gap * (rows + 1)), bg)
    for i, im in enumerate(images):
        x = gap + (i % cols) * (w + gap)
        y = gap + (i // cols) * (h + gap)
        sheet.paste(im, (x, y))
    return sheet


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--palette", choices=list(PALETTES) + ["all"],
                    default="amber")
    ap.add_argument("--scale", type=int, default=3,
                    help="agrandissement au plus proche voisin (defaut 3)")
    ap.add_argument("--out", default="esp32/mockups")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = list(PALETTES) if args.palette == "all" else [args.palette]

    for pname in names:
        pal = PALETTES[pname]
        scaled = []
        for key, fn in SCREENS.items():
            img = fn(pal).img
            img.save(out / "{}-{}-240x320.png".format(pname, key))
            # Plus proche voisin : un lissage mentirait sur le rendu final.
            big = img.resize((W * args.scale, H * args.scale), Image.NEAREST)
            big.save(out / "{}-{}.png".format(pname, key))
            scaled.append(big)
        contact_sheet(scaled).save(out / "{}-planche.png".format(pname))
        print("{:9} : {} ecrans + planche".format(pname, len(scaled)))

    print("\n{} fichiers dans {}/".format(
        len(names) * (len(SCREENS) * 2 + 1), out))
    print("Grille : {} colonnes x {} lignes (police {}x{})".format(
        COLS, ROWS, CW, CH))


if __name__ == "__main__":
    main()
