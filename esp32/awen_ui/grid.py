"""Rendu sur la grille 30x20 de l'écran, avec redessin partiel.

L'écran fait 240x320 et la police vga1_8x16 fait 8x16 pixels : la surface se
découpe donc exactement en 30 colonnes sur 20 lignes.

Le point important de ce module n'est pas de savoir écrire du texte, c'est de
savoir ne PAS le réécrire. Repeindre les 240x320 pixels coûte une trentaine de
millisecondes en MicroPython ; à une image par seconde pour une horloge, ça se
voit et ça clignote. On garde donc une copie de ce qui est réellement affiché
et, à chaque flush, on ne redessine que les cellules qui ont changé. Une
horloge qui passe de 21:47 à 21:48 ne coûte qu'une cellule.

Les caractères sont volontairement limités à l'ASCII : la police bitmap
embarquée n'a ni accents ni flèches, et un caractère absent sort en rectangle
vide. Écris « SEANCE », pas « SÉANCE ».
"""
from array import array

COLS, ROWS = 30, 20
CW, CH = 8, 16
N = COLS * ROWS

_SPACE = 32


class Grid:
    """Une grille de caractères qui se redessine le moins possible.

    display doit fournir deux méthodes seulement, ce qui rend le portage vers
    un autre pilote trivial :
        display.text(font, texte, x, y, couleur_texte, couleur_fond)
        display.fill_rect(x, y, largeur, hauteur, couleur)
    """

    def __init__(self, display, font, palette, bigfont=None):
        self.d = display
        self.f = font
        self.p = palette
        self.bigfont = bigfont

        # Ce qu'on veut voir.
        self.ch = bytearray(N)
        self.fg = array("H", [palette.FG] * N)
        self.bg = array("H", [palette.BG] * N)

        # Ce qui est réellement à l'écran. Rempli de 0xFF (impossible en
        # ASCII) pour forcer un premier tracé complet.
        self.sch = bytearray(b"\xff" * N)
        self.sfg = array("H", [0] * N)
        self.sbg = array("H", [0] * N)

        # Mémo des tracés hors grille (jauges, filets, cadres) : on ne les
        # redessine que quand leur valeur change vraiment.
        self._gfx = {}

        self.clear()

    # ---------------------------------------------------------------- texte

    def clear(self):
        """Vide la grille. Ne dessine rien : c'est flush() qui tranchera."""
        for i in range(N):
            self.ch[i] = _SPACE
            self.fg[i] = self.p.FG
            self.bg[i] = self.p.BG
        self._gfx.clear()

    def text(self, col, row, s, fg=None, bg=None):
        """Écrit sur la grille, une cellule par caractère."""
        if row < 0 or row >= ROWS:
            return
        f = self.p.FG if fg is None else fg
        b = self.p.BG if bg is None else bg
        base = row * COLS
        for i in range(len(s)):
            c = col + i
            if c < 0:
                continue
            if c >= COLS:
                break               # on tronque au bord, on ne déborde pas
            k = base + c
            o = ord(s[i])
            self.ch[k] = o if 32 <= o < 127 else _SPACE
            self.fg[k] = f
            self.bg[k] = b

    def right(self, row, s, fg=None, bg=None):
        self.text(COLS - len(s), row, s, fg, bg)

    def center(self, row, s, fg=None, bg=None):
        self.text((COLS - len(s)) // 2, row, s, fg, bg)

    def cursor(self, col, row, on=True):
        """Le bloc clignotant. C'est lui qui donne le côté vivant."""
        k = row * COLS + col
        if 0 <= k < N:
            self.ch[k] = _SPACE
            self.bg[k] = self.p.HI if on else self.p.BG

    def flush(self):
        """Envoie à l'écran les seules cellules qui ont changé.

        On regroupe les cellules voisines qui partagent les mêmes couleurs en
        une seule chaîne : un appel au pilote pour vingt caractères coûte
        beaucoup moins que vingt appels d'un caractère.
        """
        d, f = self.d, self.f
        ch, fg, bg = self.ch, self.fg, self.bg
        sch, sfg, sbg = self.sch, self.sfg, self.sbg

        for row in range(ROWS):
            base = row * COLS
            col = 0
            while col < COLS:
                k = base + col
                if ch[k] == sch[k] and fg[k] == sfg[k] and bg[k] == sbg[k]:
                    col += 1
                    continue

                # Début d'une zone sale : on l'étend tant que les couleurs
                # tiennent et que les cellules diffèrent de l'affichage.
                cf, cb = fg[k], bg[k]
                start = col
                buf = []
                while col < COLS:
                    k = base + col
                    if fg[k] != cf or bg[k] != cb:
                        break
                    if ch[k] == sch[k] and fg[k] == sfg[k] and bg[k] == sbg[k]:
                        break
                    buf.append(chr(ch[k]))
                    sch[k], sfg[k], sbg[k] = ch[k], cf, cb
                    col += 1

                d.text(f, "".join(buf), start * CW, row * CH, cf, cb)

    # ------------------------------------------------------------ graphiques
    #
    # Filets, cadres et jauges ne passent pas par la grille de caractères :
    # les tracer en rectangles est plus net et plus rapide que d'aligner des
    # caractères de remplissage.

    def rule(self, row, color=None):
        """Filet horizontal d'un pixel, en bas de la ligne indiquée."""
        key = ("rule", row)
        c = self.p.DIM if color is None else color
        if self._gfx.get(key) == c:
            return
        self._gfx[key] = c
        self.d.fill_rect(0, row * CH + CH - 1, COLS * CW, 1, c)

    def frame(self, col, row, width, height, color=None):
        """Cadre d'un pixel autour d'une zone, en coordonnées de grille."""
        key = ("frame", col, row, width, height)
        c = self.p.DIM if color is None else color
        if self._gfx.get(key) == c:
            return
        self._gfx[key] = c
        x, y = col * CW, row * CH
        w, h = width * CW, height * CH
        self.d.fill_rect(x, y, w, 1, c)
        self.d.fill_rect(x, y + h - 1, w, 1, c)
        self.d.fill_rect(x, y, 1, h, c)
        self.d.fill_rect(x + w - 1, y, 1, h, c)

    def bar(self, col, row, width, pct, color=None):
        """Jauge pleine, en blocs francs — jamais de dégradé.

        Seul le delta est repeint : une jauge de repos qui avance d'un pour
        cent ne coûte que les quelques pixels gagnés.
        """
        key = ("bar", col, row, width)
        c = self.p.FG if color is None else color
        if pct < 0:
            pct = 0
        elif pct > 100:
            pct = 100

        total = width * CW
        filled = (total * int(pct)) // 100
        prev, prevc = self._gfx.get(key, (None, None))
        if prev == filled and prevc == c:
            return

        x = col * CW
        y = row * CH + 3            # 10 px de haut, centrés dans la cellule
        h = CH - 6

        if prev is None or prevc != c:
            self.d.fill_rect(x, y, filled, h, c)
            self.d.fill_rect(x + filled, y, total - filled, h, self.p.BG)
        elif filled > prev:
            self.d.fill_rect(x + prev, y, filled - prev, h, c)
        else:
            self.d.fill_rect(x + filled, y, prev - filled, h, self.p.BG)

        self._gfx[key] = (filled, c)

    def big(self, col, row, s, fg=None):
        """Texte à la grande police (16x32), pour l'heure de l'écran de veille.

        Occupe deux colonnes et deux lignes par caractère. Sans bigfont
        déclarée, on retombe sur la police normale plutôt que de planter.
        """
        if self.bigfont is None:
            self.text(col, row, s, fg)
            return
        key = ("big", col, row)
        c = self.p.HI if fg is None else fg
        if self._gfx.get(key) == (s, c):
            return
        prev = self._gfx.get(key)
        self._gfx[key] = (s, c)
        x, y = col * CW, row * CH
        if prev is not None and len(prev[0]) > len(s):
            # Le texte a raccourci : on efface l'ancienne emprise.
            self.d.fill_rect(x, y, len(prev[0]) * 16, 32, self.p.BG)
        self.d.text(self.bigfont, s, x, y, c, self.p.BG)

    def wipe(self):
        """Efface physiquement l'écran et invalide tout.

        À appeler au changement d'écran : sans ça, les cellules de l'écran
        précédent qui se trouvent identiques ne seraient jamais repeintes.
        """
        self.d.fill_rect(0, 0, COLS * CW, ROWS * CH, self.p.BG)
        for i in range(N):
            self.sch[i] = 0xFF
            self.sfg[i] = 0
            self.sbg[i] = 0
        self._gfx.clear()
        self.clear()
