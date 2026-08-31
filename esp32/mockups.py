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
CW, CH = 8, 16          # cellule : 8 de large, 16 de haut -> 30 x 20
GLYPH = 8               # la police integree de framebuf fait 8x8
YOFF = (CH - GLYPH) // 2
COLS, ROWS = W // CW, H // CH

FONT_PATH = r"C:\Windows\Fonts\consola.ttf"
FONT_BOLD = r"C:\Windows\Fonts\consolab.ttf"

# Trois ambiances. TARS a l'ecran, c'est de l'ambre chaud sur noir absolu :
# le contraste vient du noir d'un ecran eteint, pas de la luminosite du texte.
# Doivent rester identiques a celles de esp32/awen_ui/theme.py : ces maquettes
# ne valent que si elles montrent les couleurs que la carte affichera.
PALETTES = {
    "amber":    {"name": "AMBRE", "bg": (0, 0, 0), "fg": (255, 176, 0), "dim": (128, 88, 0),
                 "hi": (255, 232, 180), "alert": (255, 64, 32)},
    "phosphor": {"name": "VERT", "bg": (0, 0, 0), "fg": (0, 255, 128), "dim": (0, 112, 56),
                 "hi": (200, 255, 224), "alert": (255, 96, 0)},
    "ice":      {"name": "BLEU", "bg": (2, 6, 10), "fg": (120, 200, 255), "dim": (40, 78, 104),
                 "hi": (230, 245, 255), "alert": (255, 96, 96)},
    "violet":   {"name": "VIOLET", "bg": (4, 0, 8), "fg": (198, 130, 255), "dim": (88, 52, 120),
                 "hi": (238, 220, 255), "alert": (255, 96, 128)},
    "rubis":    {"name": "RUBIS", "bg": (6, 0, 0), "fg": (255, 96, 96), "dim": (120, 40, 40),
                 "hi": (255, 214, 214), "alert": (255, 176, 0)},
    "papier":   {"name": "PAPIER", "bg": (0, 0, 0), "fg": (226, 226, 222), "dim": (104, 106, 104),
                 "hi": (255, 255, 255), "alert": (255, 96, 64)},
}

PALETTE_NAMES = ("AMBRE", "VERT", "BLEU", "VIOLET", "RUBIS", "PAPIER")

# Le curseur clignotant est le seul aplat trace en dur : tout le reste passe
# par des rectangles, comme sur la machine.


class Screen:
    """Un ecran 240x320 compose sur la grille 30x20."""

    def __init__(self, pal):
        self.p = pal
        self.img = Image.new("RGB", (W, H), pal["bg"])
        self.d = ImageDraw.Draw(self.img)
        # Taille calee sur la police 8x8 de la carte, pas sur ce qui est
        # joli ici : une maquette plus fine que la machine ment.
        self.font = ImageFont.truetype(FONT_PATH, 11)
        self.bold = ImageFont.truetype(FONT_BOLD, 11)

    def text(self, col, row, s, color="fg", bold=False):
        """Ecrit sur la grille, un caractere par cellule.

        Le glyphe fait 8 px de haut dans une cellule de 16 : on le centre.
        """
        f = self.bold if bold else self.font
        c = self.p[color] if isinstance(color, str) else color
        for i, ch in enumerate(s):
            if 0 <= col + i < COLS:
                self.d.text(((col + i) * CW, row * CH + YOFF - 2), ch,
                            font=f, fill=c)

    def right(self, row, s, color="fg", bold=False):
        self.text(COLS - len(s), row, s, color, bold)

    def center(self, row, s, color="fg", bold=False):
        self.text((COLS - len(s)) // 2, row, s, color, bold)

    def rule(self, row, color="dim"):
        """Filet d'un pixel, en rectangle comme grid.rule() sur la machine.

        Surtout pas un caractere de filet : a cette taille il ne remplit pas
        sa cellule et la ligne sort en pointilles.
        """
        c = self.p[color] if isinstance(color, str) else color
        y = row * CH + CH - 1
        self.d.rectangle([0, y, W - 1, y], fill=c)

    def bar(self, col, row, width, pct, color="fg"):
        """Jauge en rectangles, exactement comme grid.bar() sur la machine.

        On n'utilise PAS les caracteres de bloc : dans une police vectorielle
        ils debordent d'une cellule vers le haut et viennent percuter la ligne
        au-dessus. Surtout, le firmware trace des rectangles — une maquette
        qui dessine autre chose ment sur le resultat.
        """
        c = self.p[color] if isinstance(color, str) else color
        x, y = col * CW, row * CH + 3
        h = CH - 6
        total = width * CW
        filled = round(total * pct / 100)
        self.d.rectangle([x, y, x + filled - 1, y + h - 1], fill=c)
        if filled < total:
            ty = row * CH + CH // 2 - 1
            self.d.rectangle([x + filled, ty, x + total - 1, ty + 1],
                             fill=self.p["dim"])

    def frame(self, col, row, width, height, color="dim"):
        """Cadre d'un pixel, en rectangles \u2014 meme raison que rule()."""
        c = self.p[color] if isinstance(color, str) else color
        x, y = col * CW, row * CH
        w, h = width * CW, height * CH
        self.d.rectangle([x, y, x + w - 1, y], fill=c)
        self.d.rectangle([x, y + h - 1, x + w - 1, y + h - 1], fill=c)
        self.d.rectangle([x, y, x, y + h - 1], fill=c)
        self.d.rectangle([x + w - 1, y, x + w - 1, y + h - 1], fill=c)

    def big(self, col, row, s, scale=4, color="hi"):
        """Texte agrandi, comme le fait le pilote : un glyphe 8x8 multiplie.

        On rend petit puis on agrandit au plus proche voisin, exactement
        comme st7789_min.text(scale=N). Rendre directement une grande police
        vectorielle donnerait des courbes lisses que la carte ne produira
        jamais.
        """
        c = self.p[color] if isinstance(color, str) else color
        # Seuillage en 1 bit avant l'agrandissement : la carte n'a que des
        # pixels allumes ou eteints. Sans ca, l'antialiasing de la police
        # vectorielle produirait des bords gris que le materiel ne fera pas.
        mask = Image.new("L", (GLYPH * len(s), GLYPH), 0)
        md = ImageDraw.Draw(mask)
        for i, ch in enumerate(s):
            md.text((i * GLYPH, -2), ch, font=self.font, fill=255)
        mask = mask.point(lambda v: 255 if v > 110 else 0)
        tmp = Image.new("RGB", mask.size, self.p["bg"])
        tmp.paste(c, mask=mask)
        tmp = tmp.resize((GLYPH * len(s) * scale, GLYPH * scale), Image.NEAREST)
        self.img.paste(tmp, (col * CW, row * CH))

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
        ("VEILLE EMPLOI", "OK"), ("SPOTIFY", "..."),
    ]
    for i, (label, state) in enumerate(lines):
        r = 7 + i
        s.text(1, r, label, "dim")
        col = "fg" if state == "OK" else "dim"
        s.text(COLS - 1 - len(state), r, state, col)
    s.text(1, 13, "> demarrage", "fg")
    s.cursor(13, 13)
    s.statusbar("v3.0", "192.168.1.32")
    return s


def s_home(p):
    """Ecran de veille : l'heure domine, le reste chuchote."""
    s = Screen(p)
    s.text(0, 0, "LUN 31 AOU", "dim")
    s.right(0, "\u2588 EN LIGNE", "fg")
    s.rule(1)

    # 5 caracteres en 32x32 (echelle 4) : 160 px, centres sur 240.
    s.big(5, 3, "21:47", scale=4)

    s.rule(7)
    s.text(1, 9, "PROCHAINE SEANCE", "dim")
    s.text(1, 10, "PULL", "hi", bold=True)
    s.right(10, "dans 11 h", "fg")

    s.text(1, 12, "OFFRES DU JOUR", "dim")
    s.right(12, "3", "hi", bold=True)

    s.text(1, 14, "DERNIERE", "dim")
    s.right(14, "Legs ven 28/08", "fg")

    s.statusbar("AWEN", "A/C : ecrans")
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

    s.text(1, 11, "REPOS", "dim")
    s.text(1, 12, "00:47", "hi", bold=True)
    s.bar(8, 12, 20, 78)

    s.text(1, 14, "FAIT", "dim")
    s.bar(8, 14, 20, 45)
    s.right(15, "9 series restantes", "dim")

    s.text(1, 17, "TOURNE >  50%", "dim")     # rattrapage du potard
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

    # Aucune jauge de « confiance » : le moteur de regles n'en calcule pas,
    # et un pourcentage invente donnerait a une decoration l'autorite d'une
    # mesure. On affiche le motif reel a la place.
    s.text(1, 15, "RIR moyen 3.2 : il te", "dim")
    s.text(1, 16, "reste trop de reserve.", "dim")

    s.statusbar("[B] APPLIQUER", "sinon : ignore")
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

    s.statusbar("[B] LIGNE", "POTARD : VALEUR")
    return s


def s_jobs(p):
    """Veille emploi : trois titres, pas plus. 30 colonnes, il faut trancher."""
    s = Screen(p)
    s.header("VEILLE EMPLOI", "21:47")

    s.text(1, 3, "3", "hi", bold=True)
    s.text(3, 3, "OFFRES CE MATIN", "fg")

    # Pas de score : la veille ne note pas les offres, et afficher une jauge
    # inventee donnerait a une decoration l'autorite d'une mesure.
    offers = [
        ("DATA ENGINEER JUNIOR", "Sancare"),
        ("PRODUCT OWNER DATA", "AXA Direct Assurance"),
        ("BUSINESS ANALYST DATA", "Adone Conseil"),
    ]
    for i, (title, org) in enumerate(offers):
        r = 5 + i * 4
        s.text(0, r, ">", "dim")
        s.text(2, r, title[:26], "hi")
        s.text(2, r + 2, org[:28], "dim")

    s.statusbar("PIPELINE 09:00", "1/3")
    return s


def s_spotify(p):
    """Ce qui joue, et le volume au potard.

    C'est l'usage le plus naturel d'un potentiometre de tout le firmware : un
    volume a une position absolue, exactement comme le curseur.
    """
    s = Screen(p)
    s.header("> SPOTIFY", "21:47")

    s.text(1, 3, "MIDNIGHT CITY", "hi", bold=True)
    s.text(1, 6, "M83", "fg")
    s.text(1, 7, "Hurry Up, We're Dreaming", "dim")

    s.text(1, 10, "1:47", "dim")
    s.right(10, "4:03", "dim")
    s.bar(1, 11, 28, 44)

    s.text(1, 14, "VOLUME", "dim")
    s.right(14, " 64%", "hi", bold=True)
    s.bar(1, 15, 28, 64)

    s.statusbar("[B] PAUSE", "A/C tenu: piste")
    return s


def s_theme(p):
    """Choix de la palette, avec un apercu des cinq roles."""
    current = PALETTE_NAMES.index(p["name"])
    s = Screen(p)
    s.header("THEME", "21:47")

    s.text(1, 3, PALETTE_NAMES[current], "hi", bold=True)
    s.right(3, "{}/{}".format(current + 1, len(PALETTE_NAMES)), "dim")

    for i, name in enumerate(PALETTE_NAMES):
        r = 5 + i
        s.text(0, r, ">" if i == current else " ", "fg")
        s.text(2, r, name, "hi" if i == current else "dim")

    s.rule(12)
    s.text(1, 13, "APERCU", "dim")
    s.text(1, 14, "valeur", "hi", bold=True)
    s.text(9, 14, "donnee", "fg")
    s.text(17, 14, "etiquette", "dim")
    s.text(1, 15, "alerte", "alert")
    s.bar(9, 15, 20, 64)

    s.text(1, 17, "non enregistre", "dim")
    s.statusbar("[B] GARDER", "POTARD : TEINTE")
    return s


SCREENS = {
    "01-boot": s_boot, "02-home": s_home, "03-gym": s_gym,
    "04-spotify": s_spotify, "05-coach": s_coach,
    "06-jobs": s_jobs, "07-settings": s_settings, "08-theme": s_theme,
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
