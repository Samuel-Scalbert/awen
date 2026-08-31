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
        """Barre haute, curseur compris : c'est le seul mouvement permanent
        de l'interface, et une maquette qui l'omet donne un ecran plus mort
        que la machine."""
        self.text(0, 0, "AWEN", "fg")
        self.text(5, 0, title, "hi", bold=True)
        self.cursor(5 + len(title) + 1, 0)
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
    """Le tableau de bord. Dense a dessein.

    La police est ASCII, donc pas d'emoji : la couleur fait le travail a leur
    place, avec un marqueur colore par section.
    """
    s = Screen(p)
    s.text(0, 0, "AWEN", "fg")
    s.text(5, 0, "Lundi 31 aout", "hi", bold=True)
    s.cursor(19, 0)
    s.right(0, "S36", "dim")
    s.rule(1)

    s.big(5, 2, "19:01", scale=4)
    s.center(4, "- saint Aristide -", "dim")
    s.rule(5)

    s.text(0, 6, "=", "hi")
    s.big(2, 6, "22C", scale=2)
    s.right(6, "COUVERT", "fg")
    s.text(1, 7, "min  18   max  23", "dim")
    s.right(7, "pluie  15%", "dim")
    s.rule(8)

    s.text(0, 9, "+", "fg")
    s.text(2, 9, "SERVEUR", "dim")
    s.right(9, "2/2 SERVICES", "fg")
    s.text(2, 10, "disque 2%  ram 13%  4j 2h", "dim")

    s.text(0, 11, ">", "hi")
    s.text(2, 11, "OFFRES DU JOUR", "dim")
    s.right(11, "2", "hi", bold=True)

    s.text(0, 12, "!", "alert")
    s.text(2, 12, "COACH", "dim")
    s.right(12, "14 jours sans seance", "alert")

    s.text(0, 13, ">", "fg")
    s.text(2, 13, "ECOUTE", "dim")
    s.right(13, "M83 - Midnight City", "fg")
    s.rule(14)

    s.text(0, 15, "*", "fg")
    s.text(2, 15, "WIFI", "dim")
    s.right(15, "BON -64 dBm", "fg")
    s.text(2, 16, "192.168.1.47", "dim")

    s.statusbar("A/C : ecrans", "B tenu: accueil")
    return s


def s_gym(p):
    """Apercu de la seance a venir, avec les charges decidees par le coach.

    En lecture seule : l'afficheur est sur un bureau, pas dans la salle.
    """
    s = Screen(p)
    s.header("SEANCE 09", "21:47")

    s.big(1, 3, "PULL", scale=2)
    s.right(3, "AUJOURD HUI", "fg")

    # Le serveur rogne le nom selon la longueur de la charge, pour qu'ils ne
    # se percutent jamais sur une ligne de 30 colonnes. On montre le
    # resultat de ce calcul, pas des noms complets qui deborderaient.
    exercises = [
        ("PEC FLY / REAR DELT", "4 x 15"),
        ("SEATED ROW", "42.5 kg x 15"),
        ("TRACTIONS (ASS", "40 kg x 10"),
        ("CURL BICEPS", "12.5 kg x 12"),
        ("FACE PULL", "20 kg x 15"),
    ]
    for i, (name, detail) in enumerate(exercises):
        r = 5 + i * 2
        budget = COLS - 2 - len(detail) - 1
        s.text(0, r, ">", "dim")
        s.text(2, r, name[:budget], "hi")
        s.right(r, detail, "fg")

    s.text(1, 16, "dernier : Legs ven 28/08", "dim")
    s.text(1, 17, "TOURNE >  50%", "dim")     # rattrapage du potard
    s.statusbar("< PREC", "1/1")
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
    s.text(1, 13, "de 22.5 kg a", "dim")
    # La charge proposee est le seul chiffre qui compte : en 16x16.
    # Aucune jauge de « confiance » — le moteur de regles n'en calcule pas,
    # et un pourcentage invente donnerait a une decoration l'autorite d'une
    # mesure.
    s.big(1, 15, "20.0 KG", scale=2)

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
    # HUMOUR est selectionne au demarrage, comme dans le film — et comme
    # dans screens.py, ou Settings.sel vaut 1.
    for i, (name, val) in enumerate(params):
        r = 4 + i * 3
        focused = i == 1
        s.text(1, r, name, "hi" if focused else "fg")
        if focused:
            s.cursor(1 + len(name) + 1, r)
        s.right(r, "{:>3}%".format(val), "hi", bold=True)
        s.bar(1, r + 1, 28, val, "fg" if focused else "dim")

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
    """Ce qui joue, pochette comprise, et le volume au potard.

    La pochette est reduite a 64x64 par le serveur et envoyee en pixels
    bruts : un ESP32 ne sait pas decoder un JPEG. Elle occupe 8 colonnes sur
    4 lignes, le texte prend les 20 colonnes restantes.

    Le volume est l'usage le plus naturel d'un potentiometre de tout le
    firmware : il a une position absolue, exactement comme le curseur.
    """
    s = Screen(p)
    s.header("> SPOTIFY", "21:47")

    # Faute de vraie pochette ici, on montre son emprise exacte : 160 px de
    # cote, soit 20 colonnes sur 10 lignes, centrees. C'est cette place-la
    # qu'il faut juger, pas une image d'illustration.
    s.frame(7, 3, 16, 9)
    s.text(11, 6, "POCHETTE", "dim")
    s.text(12, 7, "112 px", "dim")

    s.big(1, 13, "MIDNIGHT CITY", scale=2)
    s.text(1, 14, "M83", "fg")

    s.text(1, 15, "1:47", "dim")
    s.right(15, "4:03", "dim")
    s.bar(1, 16, 28, 44)

    # Volume sur une seule ligne : etiquette, jauge et valeur cohabitent.
    s.text(0, 17, "VOL", "dim")
    s.bar(4, 17, 21, 64)
    s.right(17, " 64%", "hi", bold=True)

    s.statusbar("[B] PAUSE", "A/C tenu: piste")
    return s


def s_theme(p):
    """Choix de la palette, avec un apercu des cinq roles."""
    current = PALETTE_NAMES.index(p["name"])
    s = Screen(p)
    s.header("THEME", "21:47")

    s.big(1, 3, PALETTE_NAMES[current], scale=2)
    s.right(3, "{}/{}".format(current + 1, len(PALETTE_NAMES)), "dim")

    for i, name in enumerate(PALETTE_NAMES):
        r = 5 + i
        s.text(0, r, ">" if i == current else " ", "fg")
        s.text(2, r, name, "hi" if i == current else "dim")
        if i == current:
            s.cursor(2 + len(name) + 1, r)

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
