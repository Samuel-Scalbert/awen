"""Rendu sur la grille 30x20 de l'écran, avec redessin partiel.

Écrit pour le pilote maison `st7789_min.py` du dépôt esp32-desk-display, dont
l'API est :

    tft.text(chaine, x, y, color=..., bg=..., scale=1)   police 8x8 integree
    tft.fill_rect(x, y, largeur, hauteur, couleur)

LA GRILLE

240 / 8 = 30 colonnes. La police fait 8 pixels de haut, mais on prend un pas
vertical de 16 : 20 lignes, avec 8 pixels de respiration entre elles.

Ce n'est pas un gâchis de place. Une police 8x8 collée ligne contre ligne sur
40 lignes donne un pavé illisible à un mètre, et l'écran est posé sur un
bureau, pas tenu à la main. L'espacement double est aussi ce qui donne aux
terminaux leur allure — TARS n'affiche jamais de texte serré.

Le glyphe est centré verticalement dans sa cellule (+4 px).

POURQUOI TOUT CE MÉCANISME DE COPIE

Repeindre 240x320 coûte une trentaine de millisecondes en MicroPython : à une
image par seconde pour une horloge, ça clignote et ça rame. On garde donc une
copie de ce qui est réellement affiché et on ne redessine que les cellules qui
ont changé, en regroupant les voisines de mêmes couleurs en un seul appel.
Une horloge qui passe de 21:47 à 21:48 ne coûte qu'une cellule.

Les caractères sont limités à l'ASCII : la police intégrée de framebuf n'a ni
accents ni flèches. Écris « SEANCE », pas « SÉANCE ».
"""
from array import array
import os


def _readable(path, size):
    """Le fichier existe-t-il et fait-il exactement la taille attendue ?

    Vérification AVANT d'appeler le pilote, pas après. draw_image_file()
    abaisse CS puis ouvre le fichier : si l'ouverture échoue, l'écran reste
    sélectionné et le bus SPI est perdu. Mieux vaut ne pas l'appeler.
    """
    try:
        return os.stat(path)[6] == size
    except OSError:
        return False

COLS, ROWS = 30, 20
CW, CH = 8, 16          # cellule : 8 de large, 16 de haut
GLYPH = 8               # la police, elle, fait 8x8
YOFF = (CH - GLYPH) // 2
N = COLS * ROWS

_SPACE = 32
BIG_PAD = 2      # respiration au-dessus du texte agrandi


class Grid:
    """Une grille de caractères qui se redessine le moins possible."""

    def __init__(self, display, palette):
        self.d = display
        self.p = palette

        # Ce qu'on veut voir.
        self.ch = bytearray(N)
        self.fg = array("H", [palette.FG] * N)
        self.bg = array("H", [palette.BG] * N)

        # Ce qui est réellement à l'écran. Rempli de 0xFF (impossible en
        # ASCII) pour forcer un premier tracé complet.
        self.sch = bytearray(b"\xff" * N)
        self.sfg = array("H", [0] * N)
        self.sbg = array("H", [0] * N)

        # Mémo des tracés hors grille (jauges, filets, cadres, gros texte) :
        # on ne les redessine que quand leur valeur change vraiment.
        self._gfx = {}
        # Ces tracés sont mis en file pendant draw() et joués APRÈS la passe
        # de texte. Les exécuter tout de suite les ferait recouvrir par les
        # fonds de cellule que flush() repeint juste après : jauges et filets
        # apparaîtraient une image puis disparaîtraient.
        self._queue = []

        self.clear()

    # ---------------------------------------------------------------- texte

    def clear(self):
        """Vide la grille de caractères. Ne dessine rien : flush() tranchera.

        Le mémo des tracés hors grille (jauges, filets, cadres, gros texte)
        n'est délibérément PAS vidé ici. clear() est appelé avant chaque
        image, y compris pour le simple battement du curseur : purger le mémo
        ferait retracer toutes les jauges et tout le texte agrandi deux fois
        par seconde, ce qui se verrait comme un scintillement — précisément
        ce que le redessin partiel existe pour éviter.

        Le mémo n'est purgé qu'au changement d'écran, par _invalidate().
        """
        for i in range(N):
            self.ch[i] = _SPACE
            self.fg[i] = self.p.FG
            self.bg[i] = self.p.BG
        self._queue = []

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

        Deux appels par zone sale : un rectangle pour repeindre toute la
        hauteur de cellule, puis le texte. Le pilote ne peint le fond que sur
        les 8 pixels du glyphe ; sans le rectangle, la moitié basse d'une
        cellule garderait ce qu'il y avait avant.
        """
        d = self.d
        ch, fg, bg = self.ch, self.fg, self.bg
        sch, sfg, sbg = self.sch, self.sfg, self.sbg
        # Lignes effectivement repeintes : un tracé hors grille qui les
        # traverse vient d'être recouvert et doit être refait, même si sa
        # valeur n'a pas bougé.
        touched = bytearray(ROWS)

        for row in range(ROWS):
            base = row * COLS
            y = row * CH
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

                x = start * CW
                w = (col - start) * CW
                d.fill_rect(x, y, w, CH, cb)
                d.text("".join(buf), x, y + YOFF, color=cf, bg=cb)
                touched[row] = 1

        self._run_queue(touched)


    # ---- mise en file : le trace reel a lieu dans flush(), apres le texte --

    def rule(self, row, color=None):
        self._queue.append(("rule", (row, color)))

    def frame(self, col, row, width, height, color=None):
        self._queue.append(("frame", (col, row, width, height, color)))

    def bar(self, col, row, width, pct, color=None):
        self._queue.append(("bar", (col, row, width, pct, color)))

    def big(self, col, row, s, scale=2, fg=None):
        self._queue.append(("big", (col, row, s, scale, fg)))

    def image(self, col, row, src, size, tag):
        """Image RGB565 déjà inversée pour ce panneau.

        `src` est soit un chemin de fichier — le pilote le fait alors défiler
        par tranches, sans jamais le charger entièrement — soit un tampon en
        mémoire pour les petites images.

        `tag` identifie le contenu : tant qu'il ne change pas, rien ne repart
        sur le bus SPI. Une pochette reste affichée plusieurs minutes ; la
        retracer à chaque image serait le plus gros gaspillage du firmware.
        """
        kind = "imagefile" if isinstance(src, str) else "image"
        self._queue.append((kind, (col, row, src, size, tag)))

    _SPAN = {"rule": 1, "frame": None, "bar": 1, "big": None}

    def _run_queue(self, touched):
        """Joue les tracés hors grille, une fois le texte posé.

        L'ordre compte : flush() repeint le fond de chaque cellule modifiée,
        et une jauge tracée avant serait recouverte. C'est ce qui faisait
        disparaître toutes les barres et tous les filets de l'afficheur.

        `touched` dit quelles lignes viennent d'être repeintes : le mémo y est
        oublié, sinon un tracé recouvert serait considéré comme encore à
        l'écran et ne reviendrait jamais.
        """
        for kind, args in self._queue:
            self._forget_if_touched(kind, args, touched)
        for kind, args in self._queue:
            if kind == "rule":
                self._draw_rule(*args)
            elif kind == "frame":
                self._draw_frame(*args)
            elif kind == "bar":
                self._draw_bar(*args)
            elif kind == "image":
                self._draw_image(*args)
            elif kind == "imagefile":
                self._draw_image_file(*args)
            else:
                self._draw_big(*args)
        self._queue = []

    def _forget_if_touched(self, kind, args, touched):
        if kind == "rule":
            rows, key = (args[0],), ("rule", args[0])
        elif kind == "frame":
            col, row, w, h = args[0], args[1], args[2], args[3]
            rows, key = range(row, row + h), ("frame", col, row, w, h)
        elif kind == "bar":
            rows, key = (args[1],), ("bar", args[0], args[1], args[2])
        elif kind in ("image", "imagefile"):
            col, row, size = args[0], args[1], args[3]
            span = max(1, size // CH)
            rows, key = range(row, row + span), ("image", col, row)
        else:
            col, row, scale = args[0], args[1], args[3]
            span = max(1, (GLYPH * scale) // CH)
            rows, key = range(row, row + span), ("big", col, row)
        for r in rows:
            if 0 <= r < ROWS and touched[r]:
                self._gfx.pop(key, None)
                return

    # ------------------------------------------------------------ graphiques
    #
    # Filets, cadres, jauges et gros texte ne passent pas par la grille de
    # caractères : les tracer directement est plus net et plus rapide.

    def _draw_rule(self, row, color=None):
        """Filet horizontal d'un pixel, en bas de la ligne indiquée."""
        key = ("rule", row)
        c = self.p.DIM if color is None else color
        if self._gfx.get(key) == c:
            return
        self._gfx[key] = c
        self.d.fill_rect(0, row * CH + CH - 1, COLS * CW, 1, c)

    def _draw_frame(self, col, row, width, height, color=None):
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

    def _draw_bar(self, col, row, width, pct, color=None):
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
        ty = row * CH + CH // 2 - 1  # rail de 2 px pour la partie vide

        def _empty(x0, w):
            """Efface puis retrace le rail : sans rail, une jauge à 5 % ne
            laisse pas deviner jusqu'où elle peut monter."""
            if w <= 0:
                return
            self.d.fill_rect(x0, y, w, h, self.p.BG)
            self.d.fill_rect(x0, ty, w, 2, self.p.DIM)

        if prev is None or prevc != c:
            self.d.fill_rect(x, y, filled, h, c)
            _empty(x + filled, total - filled)
        elif filled > prev:
            self.d.fill_rect(x + prev, y, filled - prev, h, c)
        else:
            _empty(x + filled, prev - filled)

        self._gfx[key] = (filled, c)

    def _draw_image_file(self, col, row, path, size, tag):
        """Fait défiler un fichier RGB565 vers l'écran, sans le charger.

        C'est draw_image_file() du pilote, qui lit par tranches de 2 Ko : une
        pochette de 51 Ko passe donc sans jamais occuper plus d'un kilo-octet
        de RAM. Sans ça, elle ne pourrait pas dépasser 64 pixels de côté.
        """
        key = ("image", col, row)
        state = (tag, path is not None)
        if self._gfx.get(key) == state:
            return
        self._gfx[key] = state
        x, y = col * CW, row * CH
        if path is None or not _readable(path, size * size * 2):
            self._gfx.pop(key, None)     # on réessaiera quand il sera là
            self.d.fill_rect(x, y, size, size, self.p.BG)
            return
        try:
            self.d.draw_image_file(path, x, y, size, size)
        except Exception as e:
            # Le pilote abaisse CS avant d'ouvrir le fichier et ne le
            # relève qu'à la fin : une exception au milieu laisse l'écran
            # sélectionné pour toujours et bloque le bus. On le relève
            # nous-mêmes plutôt que de figer l'afficheur.
            print("image:", e)
            try:
                self.d.cs.value(1)
            except Exception:
                pass
            self._gfx.pop(key, None)
            self.d.fill_rect(x, y, size, size, self.p.BG)

    def _draw_image(self, col, row, buf, size, tag):
        # Le mémo retient AUSSI la présence du tampon. Sans ça, l'affichage
        # d'un emplacement vide en attendant le téléchargement mémoriserait
        # déjà l'étiquette, et l'image arrivée ensuite — même étiquette — ne
        # serait jamais tracée. C'est ce qui laissait la pochette absente.
        key = ("image", col, row)
        state = (tag, buf is not None)
        if self._gfx.get(key) == state:
            return
        self._gfx[key] = state
        if buf is None:
            self.d.fill_rect(col * CW, row * CH, size, size, self.p.BG)
            return
        self.d.blit_buffer(buf, col * CW, row * CH, size, size)

    def _draw_big(self, col, row, s, scale=2, fg=None):
        """Texte agrandi : le pilote multiplie le glyphe 8x8 par `scale`.

        scale=2 donne du 16x16, qui remplit exactement la hauteur d'une
        cellule et occupe deux colonnes par caractère. scale=4 donne du
        32x32, deux lignes de haut : c'est l'horloge de l'écran de veille.

        Le tracé sort de la grille de caractères, donc le suivi cellule par
        cellule ne peut pas l'effacer. On mémorise ce qui a été écrit pour
        pouvoir le faire soi-même — passer une chaîne vide efface la zone,
        ce dont on a besoin quand une valeur disparaît sans changement
        d'écran.
        """
        key = ("big", col, row)
        c = self.p.HI if fg is None else fg
        prev = self._gfx.get(key)
        if prev == (s, c, scale):
            return

        # Deux pixels de respiration : sans eux, un texte agrandi placé
        # juste sous un filet le touche, et l'écran semble tassé.
        x, y = col * CW, row * CH + BIG_PAD
        gw = GLYPH * scale
        if prev is not None and len(prev[0]) > len(s):
            # Le texte a raccourci ou disparu : on efface l'ancienne emprise,
            # sinon « 9:05 » laisserait un chiffre orphelin de « 12:05 ».
            self.d.fill_rect(x, y, len(prev[0]) * GLYPH * prev[2],
                             GLYPH * prev[2], self.p.BG)
        if not s:
            self._gfx.pop(key, None)
            return
        self._gfx[key] = (s, c, scale)
        self.d.text(s, x, y, color=c, bg=self.p.BG, scale=scale)

    def _invalidate(self):
        """Oublie ce qui est à l'écran : le prochain flush repeindra tout."""
        for i in range(N):
            self.sch[i] = 0xFF
            self.sfg[i] = 0
            self.sbg[i] = 0
        self._gfx.clear()
        self.clear()

    def wipe(self):
        """Efface physiquement l'écran et invalide tout, sans transition."""
        self.d.fill_rect(0, 0, COLS * CW, ROWS * CH, self.p.BG)
        self._invalidate()

    def sweep(self, delay_ms=14):
        """Balaye l'écran d'une ligne lumineuse, du haut vers le bas.

        Remplace l'effacement instantané au changement d'écran. Repeindre les
        240x320 d'un coup produit un flash noir qui se lit comme un gel de
        l'affichage : rien ne bouge, puis tout a change. Une ligne qui
        descend prend le meme temps mais raconte ce qui se passe, et c'est le
        genre de transition que fait une machine, pas une application.

        L'attente est ici plutot que dans la boucle principale parce qu'un
        balayage doit rester regulier : le decouper en images le rendrait
        dependant de la charge du reste du firmware.
        """
        from time import sleep_ms
        w = COLS * CW
        for row in range(ROWS):
            y = row * CH
            self.d.fill_rect(0, y, w, CH, self.p.BG)
            if row + 1 < ROWS:
                self.d.fill_rect(0, y + CH, w, 2, self.p.FG)
            sleep_ms(delay_ms)
        self.d.fill_rect(0, (ROWS - 1) * CH + CH - 2, w, 2, self.p.BG)
        self._invalidate()

    def set_palette(self, palette):
        """Change de palette à chaud, en repeignant tout.

        Les couleurs sont recopiées dans les tampons : sans ça, les cellules
        inchangées garderaient l'ancienne teinte et l'écran finirait bicolore.
        """
        self.p = palette
        for i in range(N):
            self.fg[i] = palette.FG
            self.bg[i] = palette.BG
        self.wipe()
