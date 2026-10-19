"""Dessin au pixel sur l'écran, avec la mémoire de ce qui s'y trouve.

Écrit pour le pilote `st7789_min.py` du dépôt esp32-desk-display. Deux de
ses méthodes suffisent :

    tft.fill_rect(x, y, largeur, hauteur, couleur)
    tft.blit_buffer(tampon, x, y, largeur, hauteur)

plus `draw_image_file` pour la pochette, qui ne tient pas en mémoire.

CE QUI A REMPLACÉ LA GRILLE

L'afficheur dessinait sur une grille de 30 x 20 caractères, dans la seule
police du pilote, une 8x8. Les trois pages demandent autre chose : des
polices proportionnelles avec accents, des chiffres à segments, des barres
arrondies. Elles se dessinent ici, au pixel.

CHAQUE ÉLÉMENT A UNE CLÉ, ET L'ÉCRAN S'EN SOUVIENT

Repeindre 240x320 prend une trentaine de millisecondes : à chaque minute
d'horloge, cela clignoterait. Chaque élément porte donc une clé, et le
canevas retient ce qu'il a tracé sous cette clé. Redemander la même chose
ne coûte qu'une comparaison ; demander autre chose ne repeint que cet
élément-là. Une page peut ainsi redessiner « tout » à chaque changement
sans y penser : seul ce qui a bougé part sur le bus.

Corollaire : sous une clé, la position ne change pas, sauf pour le texte
et les quelques formes mobiles, qui effacent eux-mêmes leur ancienne place.
Au changement de page, wipe() ou sweep() oublient tout.

LE TEXTE EST COMPOSÉ EN ENTIERS

Une ligne de pixels du texte est un grand entier, un bit par pixel ; poser
un glyphe, c'est un décalage et un OU. MicroPython sait faire, et le même
code tourne sur un PC : `esp32/simulateur.py` rend les pages avec ce
fichier-ci, pas avec une copie.

Les bits sont ensuite traduits en RGB565 par paquets de quatre, à travers
une table de seize entrées par couple de couleurs. Pixel par pixel, une
ligne de titre demanderait deux cents affectations ; par quartets,
cinquante.
"""
import math
import os

import logo as logo_mod

W, H = 240, 320

# Le panneau inverse ses couleurs, et le pilote le corrige dans fill_rect,
# mais blit_buffer envoie les octets tels quels. Tout ce qui passe par un
# tampon est donc inversé ici, comme le serveur le fait pour la pochette.
_XOR = 0xFFFF

_TAMPON = 1920          # quatre lignes de 240 pixels, alloué une seule fois
_LUTS_MAX = 8


def largeur(font, s):
    """Largeur du texte, en pixels : la somme des avances."""
    chars, offs, data = font[0], font[1], font[2]
    n = 0
    for ch in s:
        i = chars.find(ch)
        if i < 0:
            i = chars.find("?")
            if i < 0:
                continue
        n += data[(offs[2 * i] << 8) | offs[2 * i + 1]]
    return n


def coupe(font, s, maxw):
    """Raccourcit le texte pour qu'il tienne dans `maxw` pixels."""
    if largeur(font, s) <= maxw:
        return s
    reste = maxw - largeur(font, "...")
    chars, offs, data = font[0], font[1], font[2]
    n = 0
    for k in range(len(s)):
        i = chars.find(s[k])
        if i < 0:
            i = chars.find("?")
        a = data[(offs[2 * i] << 8) | offs[2 * i + 1]] if i >= 0 else 0
        if n + a > reste:
            return s[:k].rstrip() + "..."
        n += a
    return s


def trame(font, s):
    """Le texte en lignes de bits. Renvoie (lignes, largeur, hauteur, dx).

    `lignes` contient un entier par ligne de pixels, bit fort à gauche.
    `dx` est négatif quand le premier glyphe déborde à gauche de sa plume,
    le « j » de FreeSans par exemple : c'est le décalage à ajouter à x.
    """
    chars, offs, data, montant, jambage = font
    pen = x0 = x1 = 0
    pos = []
    for ch in s:
        i = chars.find(ch)
        if i < 0:
            i = chars.find("?")
            if i < 0:
                continue
        o = (offs[2 * i] << 8) | offs[2 * i + 1]
        w = data[o + 1]
        if w:
            g = pen + data[o + 3] - 128
            if g < x0:
                x0 = g
            if g + w > x1:
                x1 = g + w
        pos.append(o)
        pos.append(pen)
        pen += data[o]
    if pen > x1:
        x1 = pen

    tw = x1 - x0
    th = montant + jambage
    rows = [0] * th
    for n in range(0, len(pos), 2):
        o = pos[n]
        w = data[o + 1]
        if not w:
            continue
        nb = (w + 7) >> 3
        droite = tw - (pos[n + 1] + data[o + 3] - 128 - x0) - w
        perdu = nb * 8 - w
        r = montant - data[o + 4] + 128
        k = o + 5
        for _ in range(data[o + 2]):
            v = 0
            for b in range(nb):
                v = (v << 8) | data[k + b]
            k += nb
            if v and 0 <= r < th:
                rows[r] |= (v >> perdu) << droite
            r += 1
    return rows, tw, th, x0


def _lisible(path, size):
    """Le fichier existe-t-il et fait-il exactement la taille attendue ?

    Vérifié AVANT d'appeler le pilote : draw_image_file() abaisse CS puis
    ouvre le fichier, et si l'ouverture échoue l'écran reste sélectionné.
    """
    try:
        return os.stat(path)[6] == size
    except OSError:
        return False


class Canvas:
    """L'écran, vu comme une liste d'éléments nommés."""

    def __init__(self, display, palette):
        self.d = display
        self.p = palette
        self._m = {}                    # clé -> ce qui est tracé
        self._buf = bytearray(_TAMPON)
        self._luts = {}
        self._ins = {}
        self._logo_buf = None

    # ------------------------------------------------------------ mémoire

    def forget(self, *keys):
        """Oublie des éléments : ils seront retracés à la prochaine demande."""
        for k in keys:
            self._m.pop(k, None)

    def forget_all(self):
        """Oublie tout sans rien effacer : la prochaine page repeint chaque
        élément sur lui-même. C'est la réparation périodique d'app.py."""
        self._m.clear()

    def wipe(self):
        """Efface l'écran et oublie tout, sans transition."""
        self.d.fill_rect(0, 0, W, H, self.p.BG)
        self._m.clear()

    def sweep(self, delay_ms=14):
        """Balaye l'écran d'une ligne lumineuse, du haut vers le bas.

        Repeindre les 240x320 d'un coup produit un flash noir qui se lit
        comme un gel : rien ne bouge, puis tout a changé. Une ligne qui
        descend prend le même temps mais raconte ce qui se passe.
        """
        from time import sleep_ms
        pas = 16
        for y in range(0, H, pas):
            self.d.fill_rect(0, y, W, pas, self.p.BG)
            if y + pas < H:
                self.d.fill_rect(0, y + pas, W, 2, self.p.FG)
            sleep_ms(delay_ms)
        self._m.clear()

    # -------------------------------------------------------------- texte

    def _lut(self, fg, bg):
        key = (fg << 16) | bg
        t = self._luts.get(key)
        if t is None:
            if len(self._luts) >= _LUTS_MAX:
                self._luts.clear()
            f, b = fg ^ _XOR, bg ^ _XOR
            on = bytes((f >> 8, f & 0xFF))
            off = bytes((b >> 8, b & 0xFF))
            t = tuple((on if i & 8 else off) + (on if i & 4 else off) +
                      (on if i & 2 else off) + (on if i & 1 else off)
                      for i in range(16))
            self._luts[key] = t
        return t

    def text(self, key, x, base, s, font, color, align=0, maxw=0, bg=None):
        """Écrit `s`, ligne de base en `base`.

        align : 0 à gauche de x, 1 à droite (x est alors le bord droit),
        2 centré sur x. `maxw` raccourcit un texte trop long. `bg` sert
        quand le texte est posé sur une forme colorée.

        Remplacer un texte par un autre efface l'ancien dans le même envoi :
        la zone repeinte couvre les deux, jamais de lettres orphelines ni de
        passage par le noir.
        """
        if bg is None:
            bg = self.p.BG
        m = self._m.get(key)
        if (m is not None and m[0] == s and m[1] == color and m[2] == x
                and m[5] == bg):
            return

        t = coupe(font, s, maxw) if (maxw and s) else s
        rows, w, h, dx = trame(font, t)
        if align:
            n = largeur(font, t)
            left = x + dx - (n if align == 1 else n // 2)
        else:
            left = x + dx
        a, b = left, left + w
        if m is not None and m[4]:
            if m[3] < a:
                a = m[3]
            if m[3] + m[4] > b:
                b = m[3] + m[4]
        if a < 0:
            a = 0
        if b > W:
            b = W
        if b > a:
            self._blit(rows, w, left - a, a, base - font[3], b - a, h,
                       color, bg)
        self._m[key] = [s, color, x, left, w, bg]

    def value(self, key, x, base, s, font, color, unit="", ufont=None,
              ucolor=0, gap=3, deg=0):
        """Un nombre et ce qui le suit : son unité, ou le signe degré.

        Les deux forment UN élément, et c'est tout l'intérêt. Tracés à
        part, l'unité devrait s'effacer de son ancienne place chaque fois
        que le nombre change de largeur. Or cette place, c'est justement
        là que le nombre vient de s'étendre : « 9° » devenant « 10° »
        perdait un morceau de son zéro.

        `deg` est l'ordonnée du signe degré, un petit cercle ; à zéro,
        c'est `unit` qui suit, dans sa police et sa couleur.
        """
        m = self._m.get(key)
        if (m is not None and m[0] == s and m[1] == color and m[2] == unit
                and m[3] == ucolor):
            return
        bg = self.p.BG
        rows, w, h, dx = trame(font, s)
        top = base - font[3]
        if w:
            self._blit(rows, w, 0, x + dx, top, w, h, color, bg)
        fin = x + dx + w
        # La largeur retenue est celle de l'ENCRE, pas la somme des avances :
        # le « % » déborde d'un pixel à droite de la sienne, et ce pixel-là
        # restait à l'écran quand l'unité disparaissait.
        if deg:
            total = w + 9
        elif unit:
            r2, w2, h2, dx2 = trame(ufont, unit)
            total = w + gap + dx2 + w2
        else:
            total = w
        loin = total
        if m is not None and m[4] > loin:
            loin = m[4]
        if loin > w:
            self.d.fill_rect(fin, top, loin - w, h, bg)
        if deg:
            self._ring(fin + 5, deg, 3, ucolor)
        elif unit:
            self._blit(r2, w2, 0, fin + gap + dx2, base - ufont[3], w2, h2,
                       ucolor, bg)
        self._m[key] = [s, color, unit, ucolor, total]

    def _blit(self, rows, w, off, x, y, bw, h, color, bg):
        """Envoie un texte de largeur w, posé à `off` dans une boîte de bw."""
        lut = self._lut(color, bg)
        nn = (bw + 3) >> 2
        pad = nn * 4 - bw
        coupe_d = off + w - bw              # ce qui dépasse à droite
        if coupe_d < 0:
            shift, coupe_d = pad - coupe_d, 0
        else:
            shift = pad
        fin = 8 - pad * 2                   # octets utiles du dernier quartet
        rb = bw * 2
        buf = self._buf
        per = len(buf) // rb
        vide = lut[0] * nn
        d = self.d
        j = 0
        while j < h:
            n = per if h - j > per else h - j
            k = 0
            for r in range(j, j + n):
                v = rows[r] >> coupe_d
                if not v:
                    buf[k:k + rb] = vide[:rb]
                    k += rb
                    continue
                v <<= shift
                s = (nn - 1) * 4
                while s:
                    buf[k:k + 8] = lut[(v >> s) & 15]
                    k += 8
                    s -= 4
                buf[k:k + fin] = lut[v & 15][:fin]
                k += fin
            d.blit_buffer(memoryview(buf)[:n * rb], x, y + j, bw, n)
            j += n

    # ------------------------------------------------------------- formes

    def rect(self, key, x, y, w, h, color):
        if self._m.get(key) == color:
            return
        self._m[key] = color
        self.d.fill_rect(x, y, w, h, color)

    def frame(self, key, x, y, w, h, color):
        """Cadre d'un pixel."""
        if self._m.get(key) == color:
            return
        self._m[key] = color
        d = self.d
        d.fill_rect(x, y, w, 1, color)
        d.fill_rect(x, y + h - 1, w, 1, color)
        d.fill_rect(x, y, 1, h, color)
        d.fill_rect(x + w - 1, y, 1, h, color)

    def _insets(self, r):
        """De combien rentre chaque ligne d'un coin arrondi de rayon r."""
        t = self._ins.get(r)
        if t is None:
            t = tuple(int(r - math.sqrt(r * r - (r - i - 0.5) ** 2) + 0.5)
                      for i in range(r))
            self._ins[r] = t
        return t

    def _rr(self, x, y, w, h, r, color):
        ins = self._insets(r)
        n = 0
        while n < r and ins[n]:
            n += 1
        d = self.d
        # Les lignes qui ne rentrent pas partent en un seul bloc : un
        # segment d'horloge coûte cinq rectangles, pas un par ligne.
        d.fill_rect(x, y + n, w, h - 2 * n, color)
        for i in range(n):
            d.fill_rect(x + ins[i], y + i, w - 2 * ins[i], 1, color)
            d.fill_rect(x + ins[i], y + h - 1 - i, w - 2 * ins[i], 1, color)

    def rrect(self, key, x, y, w, h, r, color):
        """Rectangle aux coins arrondis. r = moitié du petit côté : une pilule."""
        if self._m.get(key) == color:
            return
        self._m[key] = color
        self._rr(x, y, w, h, r, color)

    def _disc(self, cx, cy, r, color):
        d = self.d
        q = (r + 0.5) * (r + 0.5)
        for dy in range(-r, r + 1):
            e = int(math.sqrt(q - dy * dy))
            d.fill_rect(cx - e, cy + dy, 2 * e + 1, 1, color)

    def disc(self, key, cx, cy, r, color):
        if self._m.get(key) == color:
            return
        self._m[key] = color
        self._disc(cx, cy, r, color)

    def ring(self, key, cx, cy, r, color):
        """Cercle d'un pixel d'épaisseur."""
        if self._m.get(key) == color:
            return
        self._m[key] = color
        self._ring(cx, cy, r, color)

    def _ring(self, cx, cy, r, color):
        d = self.d
        q, qi = (r + 0.5) * (r + 0.5), (r - 0.5) * (r - 0.5)
        for dy in range(-r, r + 1):
            e = int(math.sqrt(q - dy * dy))
            c = qi - dy * dy
            i = int(math.sqrt(c) + 0.999) - 1 if c > 0 else -1
            if 0 <= i < e:
                d.fill_rect(cx - e, cy + dy, e - i, 1, color)
                d.fill_rect(cx + i + 1, cy + dy, e - i, 1, color)
            else:
                d.fill_rect(cx - e, cy + dy, 2 * e + 1, 1, color)

    def tri(self, key, x, cy, depth, half, color):
        """Triangle couché. Sa pointe est en x ; `depth` positif place la
        base à droite (il pointe à gauche), négatif à gauche."""
        if self._m.get(key) == color:
            return
        self._m[key] = color
        d = self.d
        n = depth if depth > 0 else -depth
        for dy in range(-half, half + 1):
            a = half - (dy if dy > 0 else -dy)
            w = 1 + (n * a + half // 2) // half
            x0 = x + depth - w + 1 if depth > 0 else x + depth
            d.fill_rect(x0, cy + dy, w, 1, color)

    # ------------------------------------------------------------- jauges

    def _bar(self, x, y, w, h, filled, color, track):
        """Barre aux bouts arrondis : la partie pleine, puis le rail."""
        r = h // 2
        ins = self._insets(r)
        d = self.d
        f = x + filled
        i = 0
        while i < h:
            k = ins[i] if i < r else (ins[h - 1 - i] if h - 1 - i < r else 0)
            j = i + 1
            # Les lignes de même retrait partent ensemble.
            while j < h and k == (ins[j] if j < r else
                                  (ins[h - 1 - j] if h - 1 - j < r else 0)):
                j += 1
            a, b = x + k, x + w - k
            m = a if f < a else (b if f > b else f)
            if m > a:
                d.fill_rect(a, y + i, m - a, j - i, color)
            if b > m:
                d.fill_rect(m, y + i, b - m, j - i, track)
            i = j

    def bar(self, key, x, y, w, h, filled, color, track):
        m = self._m.get(key)
        if m is not None and m[0] == filled and m[1] == color:
            return
        self._m[key] = [filled, color]
        self._bar(x, y, w, h, filled, color, track)

    def slider(self, key, x, y, w, h, filled, color, track, kr, kcolor):
        """Une barre et son curseur rond, pour la position dans la piste."""
        m = self._m.get(key)
        if m is not None and m[0] == filled and m[1] == color:
            return
        cy = y + h // 2
        if m is not None:
            # Le curseur dépasse de la barre : son ancienne place s'efface
            # à part, puis la barre est retracée dessous.
            self.d.fill_rect(x + m[0] - kr, cy - kr, 2 * kr + 1, 2 * kr + 1,
                             self.p.BG)
        self._m[key] = [filled, color]
        self._bar(x, y, w, h, filled, color, track)
        self._disc(x + filled, cy, kr, kcolor)

    def vmeter(self, key, x, y, w, h, filled, color, track):
        """Jauge verticale, pleine depuis le bas : le volume.

        La partie pleine et le rail sont deux rectangles qui ne se
        recouvrent pas : tourner la molette ne fait jamais clignoter la jauge.
        """
        m = self._m.get(key)
        if m is not None and m[0] == filled and m[1] == color:
            return
        self._m[key] = [filled, color]
        f = h if filled > h else (0 if filled < 0 else filled)
        if h - f:
            self.d.fill_rect(x, y, w, h - f, track)
        if f:
            self.d.fill_rect(x, y + h - f, w, f, color)

    def vbar(self, key, x, y, w, h, pos, size, color, track):
        """Ascenseur vertical : un rail et sa poignée."""
        m = self._m.get(key)
        if m is not None and m[0] == pos and m[1] == size and m[2] == color:
            return
        self._m[key] = [pos, size, color]
        self.d.fill_rect(x, y, w, h, track)
        if size > 0:
            self.d.fill_rect(x, y + pos, w, size, color)

    # ------------------------------------------------------------- images

    def logo(self, x, y, phase, ring):
        """Le logo Awen, image `phase`, envoyé d'un bloc.

        Atomique : le fond et le bras arrivent ensemble, donc jamais de
        bras à demi effacé le temps d'une image.
        """
        if self._m.get("logo") == phase:
            return
        self._m["logo"] = phase
        size = logo_mod.SIZE
        buf = self._logo_buf
        if buf is None:
            buf = self._logo_buf = bytearray(size * size * 2)
        bg = self.p.BG ^ _XOR
        hi, lo = bg >> 8, bg & 0xFF
        for j in range(0, len(buf), 2):
            buf[j] = hi
            buf[j + 1] = lo
        frame = logo_mod.FRAMES[phase % len(logo_mod.FRAMES)]
        for i in range(0, len(frame), 2):
            c = ring[frame[i + 1] - 1] ^ _XOR
            j = frame[i] * 2
            buf[j] = c >> 8
            buf[j + 1] = c & 0xFF
        self.d.blit_buffer(buf, x, y, size, size)

    def image(self, key, x, y, path, size, tag):
        """Fait défiler un fichier RGB565 vers l'écran, sans le charger.

        `tag` identifie le contenu : tant qu'il ne change pas, rien ne
        repart sur le bus. Une pochette reste affichée plusieurs minutes.
        Le mémo retient aussi la présence du fichier, sinon l'emplacement
        vide affiché pendant le téléchargement passerait pour l'image.
        """
        m = self._m.get(key)
        present = path is not None
        if m is not None and m[0] == tag and m[1] == present:
            return
        self._m[key] = [tag, present]
        if not present or not _lisible(path, size * size * 2):
            self._m.pop(key, None)       # on réessaiera quand il sera là
            self.d.fill_rect(x, y, size, size, self.p.BG)
            return
        try:
            self.d.draw_image_file(path, x, y, size, size)
        except Exception as e:
            # Le pilote abaisse CS avant d'ouvrir le fichier : une exception
            # au milieu laisse l'écran sélectionné et bloque le bus. On le
            # relève nous-mêmes plutôt que de figer l'afficheur.
            print("image:", e)
            try:
                self.d.cs.value(1)
            except Exception:
                pass
            self._m.pop(key, None)
            self.d.fill_rect(x, y, size, size, self.p.BG)
