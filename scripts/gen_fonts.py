"""Génère esp32/awen_ui/fonts.py : les polices bitmap de l'afficheur.

    python scripts/gen_fonts.py dossier_des_ttf [--apercu fichier.png]

Le pilote de l'écran n'a qu'une police 8x8. Les pages ont besoin de vraies
polices proportionnelles, avec les accents du français : un agenda écrit
« Séance » et « Réunion », pas « Seance ».

LES SOURCES

  FreeSans.ttf, FreeSansBold.ttf   GNU FreeFont (GPL + exception de police),
                                   https://ftp.gnu.org/gnu/freefont/
  la 5x7                           le jeu classique des afficheurs à matrice,
                                   recopié dans PIXEL plus bas

FreeType les rend en 1 bit avec son hinting monochrome, exactement comme le
fait `fontconvert` d'Adafruit GFX : à 13 px de haut, c'est ce hinting qui
donne des lettres nettes, pas un seuillage d'antialiasing.

LES TAILLES suivent la convention GFX, 141 points par pouce : « 9 pt » vaut
17,6 px de corps, soit 13 px de hauteur de capitale.

LE FORMAT, pensé pour MicroPython

Par police : CHARS (les caractères, dans l'ordre), OFFS (deux octets par
caractère, position de son glyphe) et DATA. Un glyphe dans DATA :

    avance, largeur, hauteur, decalage_x + 128, haut + 128
    puis `hauteur` lignes de ceil(largeur / 8) octets, bit fort à gauche

`haut` compte les lignes au-dessus de la ligne de base ; il est négatif
pour le tiret bas, qui vit entièrement dessous.

Tout tient dans des `bytes` : pas de dictionnaire, pas de liste d'objets.
Un dictionnaire de 120 glyphes coûterait trois kilo-octets de tas par
police, soit plus que les glyphes eux-mêmes.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "esp32" / "awen_ui" / "fonts.py"

ASCII = "".join(chr(c) for c in range(32, 127))
ACCENTS = "àâäçéèêëîïôöùûüÿœÀÂÇÉÈÊËÎÏÔÙÛÜŒ°"
CHIFFRES = "0123456789:,.-+/% "

# nom, fichier, corps en points GFX, caractères
POLICES = (
    ("S9", "FreeSans.ttf", 9, ASCII + ACCENTS),
    ("B9", "FreeSansBold.ttf", 9, CHIFFRES),
    ("B12", "FreeSansBold.ttf", 12, ASCII + ACCENTS),
    ("B18", "FreeSansBold.ttf", 18, CHIFFRES),
)

# La petite capitale 5x7 des libellés. Cinq colonnes par caractère, bit 0 en
# haut : c'est le dessin classique des afficheurs à matrice, celui qu'on
# retrouve sur les instruments. Majuscules, chiffres et ponctuation utile
# seulement : les libellés sont écrits par le firmware, jamais par l'agenda.
PIXEL = {
    " ": "0000000000", "!": "00005F0000", "'": "0005030000", "%": "2313086462",
    "+": "08083E0808", ",": "0050300000", "-": "0808080808", ".": "0060600000",
    "/": "2010080402", ":": "0036360000", "<": "0814224100", ">": "0041221408",
    "?": "0201510906",
    "0": "3E5149453E", "1": "00427F4000", "2": "4261514946", "3": "2141454B31",
    "4": "1814127F10", "5": "2745454539", "6": "3C4A494930", "7": "0171090503",
    "8": "3649494936", "9": "064949291E",
    "A": "7E1111117E", "B": "7F49494936", "C": "3E41414122", "D": "7F4141221C",
    "E": "7F49494941", "F": "7F09090901", "G": "3E4149497A", "H": "7F0808087F",
    "I": "00417F4100", "J": "2040413F01", "K": "7F08142241", "L": "7F40404040",
    "M": "7F020C027F", "N": "7F0408107F", "O": "3E4141413E", "P": "7F09090906",
    "Q": "3E4151215E", "R": "7F09192946", "S": "4649494931", "T": "01017F0101",
    "U": "3F4040403F", "V": "1F2040201F", "W": "3F4038403F", "X": "6314081463",
    "Y": "0708700807", "Z": "6151494543",
}


def corps_px(points):
    return points * 141 / 72


def glyphes_ttf(chemin, points, chars):
    """[(car, avance, largeur, hauteur, dx, haut, lignes)] et (montant, jambage)."""
    font = ImageFont.truetype(str(chemin), corps_px(points))
    marge = int(corps_px(points)) + 8
    cote = marge * 3
    out, montant, jambage = [], 0, 0
    for ch in chars:
        im = Image.new("1", (cote, cote), 0)
        d = ImageDraw.Draw(im)
        d.fontmode = "1"
        d.text((marge, marge * 2), ch, fill=1, font=font, anchor="ls")
        avance = int(round(font.getlength(ch, mode="1")))
        boite = im.getbbox()
        if boite is None:                       # l'espace
            out.append((ch, avance, 0, 0, 0, 0, []))
            continue
        x0, y0, x1, y1 = boite
        w, h = x1 - x0, y1 - y0
        haut = marge * 2 - y0                   # lignes au-dessus de la base
        px = im.load()
        lignes = []
        for y in range(y0, y1):
            v = 0
            for x in range(x0, x1):
                v = (v << 1) | (1 if px[x, y] else 0)
            lignes.append(v)
        out.append((ch, avance, w, h, x0 - marge, haut, lignes))
        montant = max(montant, haut)
        jambage = max(jambage, h - haut)
    return out, montant, jambage


def glyphes_pixel():
    out = []
    for ch in sorted(PIXEL):
        cols = bytes.fromhex(PIXEL[ch])
        lignes = []
        for y in range(7):
            v = 0
            for c in cols:
                v = (v << 1) | ((c >> y) & 1)
            lignes.append(v)
        out.append((ch, 6, 5, 7, 0, 7, lignes))
    return out, 7, 0


def emballe(glyphes):
    chars, offs, data = "", bytearray(), bytearray()
    for ch, avance, w, h, dx, haut, lignes in glyphes:
        chars += ch
        offs += len(data).to_bytes(2, "big")
        data += bytes((avance, w, h, dx + 128, haut + 128))
        nb = (w + 7) // 8
        for v in lignes:
            data += (v << (nb * 8 - w)).to_bytes(nb, "big")
    return chars, bytes(offs), bytes(data)


def litteral(b, largeur=64):
    """Des `bytes` lisibles par mpy-cross, coupés en lignes courtes."""
    morceaux = [b[i:i + largeur] for i in range(0, len(b), largeur)]
    return "(\n" + "".join("    {!r}\n".format(m) for m in morceaux) + ")"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    dossier = Path(sys.argv[1])
    apercu = sys.argv[sys.argv.index("--apercu") + 1] if "--apercu" in sys.argv else None

    polices = []
    for nom, fichier, points, chars in POLICES:
        glyphes, montant, jambage = glyphes_ttf(dossier / fichier, points, chars)
        polices.append((nom, glyphes, montant, jambage, "{} {} pt".format(fichier, points)))
    glyphes, montant, jambage = glyphes_pixel()
    polices.append(("PX", glyphes, montant, jambage, "capitale 5x7"))

    lignes = ['"""Polices bitmap de l\'afficheur.',
              "",
              "GENERE PAR scripts/gen_fonts.py : NE PAS EDITER A LA MAIN.",
              "",
              "Le format est decrit dans le generateur. Chaque police est un",
              "tuple (CHARS, OFFS, DATA, montant, jambage) : canvas.py n'en lit",
              "jamais plus.",
              '"""', ""]
    total = 0
    for nom, glyphes, montant, jambage, source in polices:
        chars, offs, data = emballe(glyphes)
        total += len(offs) + len(data)
        lignes.append("# {} : {}, {} glyphes, {} octets".format(
            nom, source, len(chars), len(offs) + len(data)))
        lignes.append("{} = ({!r}, {}, {}, {}, {})".format(
            nom, chars, litteral(offs), litteral(data), montant, jambage))
        lignes.append("")
        print("{:4} {:24} {:3} glyphes  {:5} octets  montant {:2}  jambage {}".format(
            nom, source, len(chars), len(offs) + len(data), montant, jambage))
    SORTIE.write_text("\n".join(lignes), encoding="utf-8")
    print("->", SORTIE, "|", total, "octets de glyphes")

    if apercu:
        sys.path.insert(0, str(SORTIE.parent))
        import canvas
        import fonts
        essais = (("S9", "Mardi 13 octobre  Séance à 18 h, déjà ?"),
                  ("B9", "09:41  18:30  12/19"),
                  ("B12", "Around the World  Été"),
                  ("B18", "21 18 15 64"),
                  ("PX", "AUJOURD'HUI  DANS 1 H 19  72/120 CM"))
        im = Image.new("RGB", (330, 150), (0, 0, 0))
        y = 6
        for nom, texte in essais:
            f = getattr(fonts, nom)
            largeur = canvas.largeur(f, texte)
            rows, w, h, _dx = canvas.trame(f, texte)
            for j, v in enumerate(rows):
                for i in range(w):
                    if (v >> (w - 1 - i)) & 1:
                        im.putpixel((6 + i, y + j), (242, 232, 208))
            print("  {:4} {!r} : {} px de large".format(nom, texte[:16], largeur))
            y += h + 6
        im.resize((990, 450), Image.NEAREST).save(apercu)
        print("->", apercu)


if __name__ == "__main__":
    main()
