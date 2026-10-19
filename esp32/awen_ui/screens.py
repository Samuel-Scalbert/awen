"""Les trois pages d'Awen : Accueil, Spotify, Calendrier.

Chaque page expose :
    NAME                 libellé court, pour la trace série
    draw(c, st, app)     décrit toute la page au canevas, à chaque changement
    on_input(ev, app)    renvoie True si l'événement a été absorbé
    on_turn(delta, app)  un cran d'encodeur : delta vaut -1 ou +1
    tick(now, app)       appelé à chaque image, pour ce qui dépend du temps

DESSINER TOUT, À CHAQUE FOIS

draw() ne cherche jamais ce qui a changé : elle redit la page entière, et
c'est le canevas qui ne repeint que les éléments différents. Une page reste
ainsi une simple description, lisible de haut en bas comme sa maquette.

La contrepartie : un élément qui disparaît doit être redit vide : un texte
"" efface l'ancien, une forme se repeint de la couleur du fond. D'où les
boucles qui parcourent toujours toutes les lignes, pleines ou non.

LES COORDONNÉES SONT CELLES DES MAQUETTES

Les pages ont été dessinées dans Lopaka (esp32/mockups/lopaka/). Les
nombres qui suivent en viennent tels quels : marges à 16 et 224, bandeau
sur 26 pixels, pied à partir de 292.
"""
import time

import backlight as backlight_mod
import fonts
from input import BTN_A, BTN_B, BTN_C, REPEAT, SHORT
import theme

PX, S9, B9, B12, B18 = fonts.PX, fonts.S9, fonts.B9, fonts.B12, fonts.B18

G, D = 16, 224                  # bords gauche et droit du contenu
LOGO_X, LOGO_Y = G, 5           # le logo du bandeau ; app.py l'anime
LARGE = D - G

_WIFI = ("b.w0", "b.w1", "b.w2", "b.w3")
_PAGES = ("p.0", "p.1", "p.2")


def _hhmm(m):
    return "--:--" if m is None else "{:02d}:{:02d}".format(m // 60, m % 60)


def _mmss(seconds):
    seconds = int(seconds)
    return "{}:{:02d}".format(seconds // 60, seconds % 60)


def _bandeau(c, nom, st, app, heure=True):
    """Le bandeau du haut, commun aux trois pages.

    Le logo, la marque, le nom de la page, puis à droite l'heure et le wifi.
    L'accueil coupe l'heure, déjà en grand dessous, et met à sa
    place ce que voit le sonar.

    LE LOGO EST LE SEUL MOUVEMENT PERMANENT

    Sans lui une page immobile ne se distingue pas d'une page gelée, surtout
    ici où presque rien ne bouge entre deux relevés espacés de trente
    secondes. Il tourne en 1,2 seconde : assez pour qu'on le voie vivre,
    assez lent pour qu'on ne le regarde pas. C'est app.py qui le fait
    avancer, sans repasser par draw().

    Hors ligne, le nom de la page cède la place à l'annonce : c'est
    l'endroit qu'on lit en premier, et la seule alerte qui concerne toutes
    les pages à la fois.
    """
    p = c.p
    c.logo(LOGO_X, LOGO_Y, st.get("spin", 0), theme.LOGO_RING)
    c.text("b.awen", 38, 17, "A W E N", PX, p.FG)
    if st.get("online", True):
        c.text("b.nom", 90, 17, nom, PX, p.DIM)
    else:
        c.text("b.nom", 90, 17, "HORS LIGNE", PX, p.ALERT)
    if heure:
        c.text("b.d", 198, 17, _hhmm(app.minutes()), PX, p.HI, 1)

    # Un dBm ne parle à personne : quatre barres, comme sur un téléphone.
    rssi = app.wifi_rssi()
    if rssi is None:
        n = 0
    else:
        n = 4 if rssi >= -60 else (3 if rssi >= -70 else (2 if rssi >= -80 else 1))
    for i in range(4):
        h = 3 + 2 * i
        c.rect(_WIFI[i], 207 + 5 * i, 18 - h, 3, h,
               p.DIM if i < n else p.FAINT)
    c.rect("b.filet", G, 26, LARGE, 1, p.RULE)


def _pied(c, gauche, droite, actif):
    """Le pied : où mènent A et C, et où l'on est parmi les trois pages."""
    p = c.p
    y = 306
    c.rect("p.filet", G, 292, LARGE, 1, p.RULE)
    c.tri("p.a", G, y, 6, 5, p.HI)
    c.text("p.ga", 28, y + 4, gauche, PX, p.DIM)
    c.tri("p.c", D - 1, y, -6, 5, p.HI)
    c.text("p.dr", 212, y + 4, droite, PX, p.DIM, 1)
    for i in range(3):
        c.rect(_PAGES[i], 101 + 14 * i, y - 1, 10, 3,
               p.FG if i == actif else p.FAINT)


class Screen:
    """Base commune. Par défaut, une page n'absorbe rien et ignore la molette."""

    NAME = "?"

    def draw(self, c, st, app):
        raise NotImplementedError

    def on_input(self, ev, app):
        return False

    def on_turn(self, delta, app):
        pass

    def tick(self, now, app):
        pass


# --------------------------------------------------------------------------


class Boot(Screen):
    """Amorçage. Les lignes tombent une par une : c'est tout le caractère."""

    NAME = "boot"
    CHECKS = ("RESEAU", "SERVEUR", "AGENDA", "SPOTIFY")
    _L = ("o.l0", "o.l1", "o.l2", "o.l3")
    _E = ("o.e0", "o.e1", "o.e2", "o.e3")

    def __init__(self):
        self.step = 0

    def draw(self, c, st, app):
        p = c.p
        c.logo(112, 64, st.get("spin", 0), theme.LOGO_RING)
        c.text("o.awen", 120, 102, "A W E N", PX, p.FG, 2)
        c.text("o.sous", 120, 124, "assistant personnel", S9, p.DIM, 2)
        c.rect("o.f1", G, 142, LARGE, 1, p.RULE)
        for i in range(len(self.CHECKS)):
            y = 168 + 20 * i
            if i > self.step:
                c.text(self._L[i], G, y, "", PX, p.DIM)
                c.text(self._E[i], D, y, "", PX, p.DIM, 1)
                continue
            done = i < self.step
            c.text(self._L[i], G, y, self.CHECKS[i], PX, p.DIM)
            c.text(self._E[i], D, y, "OK" if done else "...", PX,
                   p.FG if done else p.DIM, 1)
        c.text("o.go", G, 262,
               "DEMARRAGE" if self.step >= len(self.CHECKS) else "", PX, p.FG)
        c.rect("o.f2", G, 292, LARGE, 1, p.RULE)
        c.text("o.v", G, 310, "V4.0", PX, p.DIM)
        c.text("o.ip", D, 310, st.get("ip", ""), PX, p.DIM, 1)


# --------------------------------------------------------------------------
# L'horloge à segments
#
# Sept pilules par chiffre, allumées ou éteintes. Les éteintes restent
# visibles, à peine : c'est ce qui fait lire un afficheur d'instrument et non
# une police, et un « 1 » n'a plus l'air perdu dans sa case.
#
# Chaque segment est un élément du canevas : quand 09:41 devient 09:42, seuls
# les segments qui changent d'état sont repeints.

_SEG = (                        # x, y, largeur, hauteur dans une case de 36x56
    (7, 0, 22, 8),              # a  haut
    (28, 6, 8, 20),             # b  haut droit
    (28, 30, 8, 20),            # c  bas droit
    (7, 48, 22, 8),             # d  bas
    (0, 30, 8, 20),             # e  bas gauche
    (0, 6, 8, 20),              # f  haut gauche
    (7, 24, 22, 8),             # g  milieu
)
_CHIFFRES = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F)
_CASES = (16, 66, 138, 188)
_CLES = tuple("h{}{}".format(i, s) for i in range(4) for s in range(7))


def _horloge(c, m, y):
    p = c.p
    if m is None:
        a = b = d = e = 0x40                    # « --:-- »
    else:
        h, mn = m // 60, m % 60
        a, b = _CHIFFRES[h // 10], _CHIFFRES[h % 10]
        d, e = _CHIFFRES[mn // 10], _CHIFFRES[mn % 10]
    k = 0
    for bits in (a, b, d, e):
        x = _CASES[k // 7]
        for s in range(7):
            g = _SEG[s]
            c.rrect(_CLES[k], x + g[0], y + g[1], g[2], g[3], 4,
                    p.FG if (bits >> s) & 1 else p.GHOST)
            k += 1
    c.disc("h.p1", 120, y + 19, 4, p.FG)
    c.disc("h.p2", 120, y + 37, 4, p.FG)


class Home(Screen):
    """Ce qu'on lit en passant : l'heure, le temps qu'il fait, la journée.

    Trois étages sous l'horloge. La météo en trois colonnes (la pièce, le
    dehors, la pluie) parce que c'est l'écart entre les deux premières qui
    dit s'il faut ouvrir la fenêtre. Puis l'agenda du jour, quatre lignes,
    qui est avec la météo ce pour quoi on regarde cet écran.

    Une journée légère ne laisse pas la moitié de l'écran vide : s'il reste
    deux lignes ou plus, le prochain jour occupé vient les remplir, sous
    son nom et en retrait de couleur. Le soir, on voit déjà demain.

    LA MOLETTE RÈGLE LA LUMINOSITÉ

    Elle n'avait rien à faire sur l'accueil, et la luminosité n'avait plus
    de page à elle. Quatre paliers, comme avant : on ne saurait pas viser
    une valeur qu'on ne sait pas nommer. Zéro n'en fait pas partie : un
    écran éteint par un cran de trop ressemblerait à une panne. Le palier
    s'affiche deux secondes à la place du sonar, puis s'efface.
    """

    NAME = "home"
    LUM_MS = 2000
    _H = ("a.h0", "a.h1", "a.h2", "a.h3")
    _T = ("a.t0", "a.t1", "a.t2", "a.t3")
    _J = ("a.j0", "a.j1", "a.j2", "a.j3")
    _M = ("a.m0", "a.m1", "a.m2", "a.m3")
    _K = ("a.k0", "a.k1", "a.k2", "a.k3")
    _D = ("a.d0", "a.d1", "a.d2", "a.d3")
    _F = ("a.f0", "a.f1", "a.f2", "a.f3")

    def __init__(self):
        self.lum_until = None

    @staticmethod
    def _lignes(ag):
        """Les quatre lignes de l'agenda, chacune (sorte, contenu).

        e : un rendez-vous d'aujourd'hui ; m : le message d'une journée
        vide ; j : le nom du jour suivant ; d : un rendez-vous de ce jour-là.
        """
        out = [("e", e) for e in (ag.get("jour") or [])[:4]]
        if not out:
            out.append(("m", "Rien de prévu" if ag.get("ok", True)
                        else "Agenda indisponible"))
        if len(out) <= 2:
            for j in ag.get("jours") or []:
                if j.get("t") != "AUJOURD'HUI":
                    out.append(("j", (j.get("t", ""), j.get("d", ""))))
                    for e in (j.get("ev") or [])[:4 - len(out)]:
                        out.append(("d", e))
                    break
        return out

    def on_turn(self, delta, app):
        niveaux = backlight_mod.LEVELS
        actuel = app.backlight.level
        i = niveaux.index(actuel) if actuel in niveaux else len(niveaux) - 1
        j = max(0, min(len(niveaux) - 1, i + delta))
        if j != i:
            app.backlight.set_level(niveaux[j])
            backlight_mod.save(niveaux[j])
        self.lum_until = time.ticks_add(time.ticks_ms(), self.LUM_MS)
        app.dirty = True

    def tick(self, now, app):
        if (self.lum_until is not None
                and time.ticks_diff(now, self.lum_until) >= 0):
            self.lum_until = None
            app.dirty = True

    def _sonar(self, c, st, app):
        """Ce que voit le sonar, et à partir de quand l'écran s'éteint.

        La distance mesurée, puis le seuil : « me voit-il ? » et « à partir
        de quelle distance ? ». La mesure s'allume quand elle passe sous le
        seuil, ce qui répond à la première question sans comparer les deux
        nombres. Un écho perdu s'affiche « -- » et non « 0 » : zéro ferait
        croire à un obstacle collé au capteur, soit l'inverse.
        """
        p = c.p
        if self.lum_until is not None:
            # « MAX » et non « 100% » : un caractère de plus, et le texte
            # mordait sur le nom de la page.
            niveau = app.backlight.level
            c.text("b.d", 198, 17, "LUMIERE MAX" if niveau >= 100
                   else "LUMIERE {}%".format(niveau), PX, p.HI, 1)
            c.forget("b.s")             # recouvert : à retracer ensuite
            return
        sonar = getattr(app, "sonar", None)
        # Pas de capteur : rien à dire. Hors ligne non plus : l'annonce
        # prend la place, et elle compte davantage.
        if (sonar is None or not sonar.threshold
                or not st.get("online", True)):
            c.text("b.s", 156, 17, "", PX, p.DIM, 1)
            c.text("b.d", 198, 17, "", PX, p.DIM, 1)
            return
        c.text("b.d", 198, 17, "/{} CM".format(sonar.threshold), PX, p.DIM, 1)
        cm = sonar.distance
        c.text("b.s", 156, 17, str(cm) if cm > 0 else "--", PX,
               p.FG if sonar.present else p.DIM, 1)

    def draw(self, c, st, app):
        p = c.p
        # Hors ligne, l'annonce déborde sur la place du sonar : il s'efface
        # donc AVANT qu'elle s'écrive, et se réécrit APRÈS qu'elle est partie.
        en_ligne = st.get("online", True)
        if not en_ligne:
            self._sonar(c, st, app)
        _bandeau(c, "ACCUEIL", st, app, heure=False)
        if en_ligne:
            self._sonar(c, st, app)

        _horloge(c, app.minutes(), 33)
        jour = st.get("jour", {})
        c.text("j.date", G, 110, jour.get("long", ""), S9, p.HI, 0, 170)
        sem = jour.get("semaine")
        c.text("j.sem", D, 110, "S{}".format(sem) if sem else "", S9, p.DIM, 1)

        # --- le temps qu'il fait -------------------------------------------
        y = 118
        c.rect("m.f", G, y, LARGE, 1, p.RULE)
        c.rect("m.s1", 82, y + 8, 1, 51, p.RULE)
        c.rect("m.s2", 154, y + 8, 1, 51, p.RULE)

        # La pièce : le DHT11, à un mètre de toi. Précis à deux degrés près,
        # donc pas de décimale : elle serait inventée.
        ti, hi = app.sensor.reading(time.ticks_ms())
        c.text("m.l1", G, y + 15, "DEDANS", PX, p.DIM)
        c.value("m.v1", G, y + 45, "--" if ti is None else str(ti), B18,
                p.HI, ucolor=p.HI, deg=0 if ti is None else y + 24)
        c.text("m.h0", G, y + 59, "HUM", PX, p.DIM)
        c.text("m.h1", 39, y + 59, "--" if hi is None else "{}%".format(hi),
               PX, p.HI)

        m = st.get("meteo", {})
        ok = m.get("ok")
        c.text("m.l2", 90, y + 15, "DEHORS", PX, p.DIM)
        c.value("m.v2", 90, y + 45, str(m.get("now_c", 0)) if ok else "--",
                B18, p.HI, ucolor=p.HI, deg=y + 24 if ok else 0)
        c.text("m.mm", 90, y + 59,
               "{} / {}".format(m.get("min_c", 0), m.get("max_c", 0)) if ok
               else "", PX, p.DIM)

        # La pluie vire à l'alerte au-delà de 60 % : c'est le seul chiffre
        # de l'écran qui peut te faire changer de chaussures.
        pluie = m.get("rain_pct", 0) if ok else 0
        c.text("m.l3", 162, y + 15, "PLUIE", PX, p.DIM)
        # À 100, le signe ne tient plus dans la colonne : l'en-tête suffit.
        c.value("m.v3", 162, y + 45, str(pluie) if ok else "--", B18,
                p.ALERT if pluie >= 60 else p.HI,
                "%" if ok and pluie < 100 else "", S9, p.DIM)
        c.text("m.ciel", 162, y + 59, m.get("court", "") if ok else "", PX,
               p.HI)

        # --- la journée ----------------------------------------------------
        ag = st.get("agenda", {})
        c.rect("a.f", G, 182, LARGE, 1, p.RULE)
        c.text("a.titre", G, 197, "AUJOURD'HUI", PX, p.DIM)
        c.text("a.dans", D, 197, ag.get("dans", ""), PX, p.FG, 1)
        lignes = self._lignes(ag)
        for i in range(4):
            b = 218 + 22 * i
            sorte, l = lignes[i] if i < len(lignes) else ("", None)
            heure = titre = journee = message = gauche = droite = ""
            etat = 2
            if sorte in ("e", "d"):
                heure, titre, etat = l[0], l[1], l[2]
                if not heure:
                    journee = "JOURNEE"
            elif sorte == "m":
                message = l
            elif sorte == "j":
                gauche, droite = l
            if sorte == "d":
                # Le jour suivant se lit en retrait : il complète, il ne
                # rivalise pas avec aujourd'hui.
                ch = ct = p.DIM
            else:
                ch = p.PAST if etat == 0 else (p.FG if etat == 1 else p.HI)
                ct = p.PAST if etat == 0 else p.HI
            # Le repère de ce qui est en cours ou arrive, dans la marge.
            c.rect(self._M[i], 8, b - 13, 3, 13,
                   p.FG if etat == 1 and sorte == "e" else p.BG)
            # Un filet au-dessus du nom du jour suivant.
            c.rect(self._F[i], G, b - 17, LARGE, 1,
                   p.RULE if sorte == "j" else p.BG)
            # Heure, « JOURNEE », message et nom du jour se partagent la même
            # place. Ce qui s'efface passe AVANT ce qui s'écrit, sinon
            # l'effacement emporte le texte tout juste posé : deux passes.
            for passe in (True, False):
                if (not heure) == passe:
                    c.text(self._H[i], G, b, heure, B9, ch)
                if (not journee) == passe:
                    c.text(self._J[i], G, b - 3, journee, PX, p.DIM)
                if (not titre) == passe:
                    c.text(self._T[i], 72, b, titre, S9, ct, 0, 152)
                if (not gauche) == passe:
                    c.text(self._K[i], G, b - 4, gauche, PX, p.DIM)
                if (not droite) == passe:
                    c.text(self._D[i], D, b - 4, droite, PX, p.DIM, 1)
                if i == 0 and (not message) == passe:
                    c.text("a.vide", G, b, message, S9, p.PAST)

        _pied(c, "CALENDRIER", "SPOTIFY", 0)


class Spotify(Screen):
    """Ce qui joue, le volume à la molette, les pistes aux boutons.

    Un cran vaut deux pour cent : un tour complet couvre toute l'échelle,
    et le geste reste assez fin pour ajuster sans viser.

    La pochette prend la place qu'il faut, 144 px, et la colonne à sa
    droite porte le volume : sa valeur, et une jauge verticale de la hauteur
    de la pochette, un pixel par pour cent. C'est le seul réglage de la page,
    et la molette le commande. Les trois gestes sont dessinés en bas, dans
    l'ordre des boutons.
    """

    NAME = "spotify"

    VOL_STEP = 2                 # % par cran ; un tour couvre l'échelle
    _GRAD = ("s.g0", "s.g1", "s.g2", "s.g3")

    def __init__(self):
        self._mode = None
        self._joue = None
        self._sec = -1

    def on_turn(self, delta, app):
        sp = app.state.get("spotify") or {}
        if not sp.get("device"):
            return
        v = max(0, min(100, sp.get("volume", 0) + delta * self.VOL_STEP))
        app.set_volume(v)

    def tick(self, now, app):
        """Fait avancer le compteur : une seconde par seconde, sans serveur."""
        sp = app.state.get("spotify") or {}
        if not sp.get("playing"):
            return
        pos = app.play_position()
        if pos != self._sec:
            self._sec = pos
            app.dirty = True

    def draw(self, c, st, app):
        p = c.p
        sp = st.get("spotify", {})
        actif = bool(sp.get("device"))
        # Les deux états n'ont rien en commun : on repart d'un écran vide
        # plutôt que de redire vide chacun des éléments de l'autre.
        if actif != self._mode:
            if self._mode is not None:
                c.wipe()
            self._mode = actif

        _bandeau(c, "SPOTIFY", st, app)
        _pied(c, "ACCUEIL", "CALENDRIER", 1)

        if not actif:
            c.text("s.vide", G, 150, "AUCUN APPAREIL", PX, p.DIM)
            c.text("s.v1", G, 176, "Lance une lecture", S9, p.HI)
            c.text("s.v2", G, 196, "sur ton téléphone.", S9, p.HI)
            return

        # --- la pochette, 144 px, dans un contour --------------------------
        # Sans lui une pochette sombre se fond dans le noir du panneau et on
        # ne voit plus où elle commence.
        c.frame("s.cadre", G - 1, 33, 146, 146, p.RULE)
        c.image("s.pochette", G, 34, app.cover, app.COVER, sp.get("cover", ""))

        # --- le volume, en colonne ------------------------------------------
        # La jauge fait cent pixels de haut, un par pour cent, et se tient
        # contre le bord droit, à hauteur de la pochette.
        vol = sp.get("volume", 0)
        c.text("s.vl", 172, 41, "VOL", PX, p.DIM)
        c.value("s.vv", 172, 64, str(vol), B12, p.HI,
                "%" if vol < 100 else "", S9, p.DIM)
        for k in range(4):
            c.rect(self._GRAD[k], 206, 79 + 25 * k, 5, 1, p.DIM)
        c.vmeter("s.vm", 214, 79, 10, 100, vol, p.FG, p.RULE)

        # --- la piste -------------------------------------------------------
        c.text("s.titre", G, 202, sp.get("title", ""), B12, p.HI, 0, LARGE)
        c.text("s.artiste", G, 226, sp.get("artist", ""), S9, p.DIM, 0, 140)
        c.text("s.album", D, 226, sp.get("album", "").upper()[:10], PX,
               p.FAINT, 1)

        # Position extrapolée localement : le compteur avance chaque seconde
        # sans que le serveur soit interrogé plus souvent. Voir app.py.
        pos = app.play_position()
        dur = sp.get("duration_s", 0)
        c.slider("s.pos", G, 238, LARGE, 4,
                 (pos * LARGE // dur) if dur else 0, p.FG, p.RULE, 4, p.HI)
        c.text("s.t0", G, 255, _mmss(pos), PX, p.HI)
        c.text("s.t1", D, 255, _mmss(dur), PX, p.DIM, 1)

        # --- les trois gestes, dans l'ordre des boutons --------------------
        y = 270
        c.rect("s.a1", 20, y - 6, 2, 13, p.HI)
        c.tri("s.a2", 23, y, 10, 6, p.HI)
        c.text("s.a3", G, 288, "A TENU", PX, p.DIM)

        # Le bouton dit ce que B va FAIRE : en lecture il propose la pause,
        # à l'arrêt la lecture. C'est aussi ce qui dit l'état de la piste.
        joue = bool(sp.get("playing"))
        if self._joue != joue:
            self._joue = joue
            c.forget("s.b1", "s.b2", "s.b3", "s.b4", "s.b5")
        c.rrect("s.b1", 82, y - 12, 76, 24, 12, p.FG)
        if joue:
            c.rect("s.b2", 97, y - 6, 4, 13, p.BG)
            c.rect("s.b3", 105, y - 6, 4, 13, p.BG)
            c.text("s.b5", 116, y + 4, "PAUSE", PX, p.BG, 0, 0, p.FG)
        else:
            c.tri("s.b4", 107, y, -9, 6, p.BG)
            c.text("s.b5", 116, y + 4, "LIRE", PX, p.BG, 0, 0, p.FG)

        c.tri("s.c1", 217, y, -10, 6, p.HI)
        c.rect("s.c2", 218, y - 6, 2, 13, p.HI)
        c.text("s.c3", D, 288, "C TENU", PX, p.DIM, 1)

    def on_input(self, ev, app):
        """Piste précédente/suivante en MAINTENANT A ou C, pas en tapant.

        L'appui court d'A et de C navigue entre les pages, partout et sans
        exception. Les faire changer de piste ici enfermerait dans Spotify :
        les trois boutons seraient pris, et seul l'appui long en sortirait.
        Maintenir pour sauter une piste est en plus le geste des autoradios.
        """
        kind, arg = ev
        if kind == BTN_B and arg == SHORT:
            app.spotify("toggle")
            return True
        if arg == REPEAT and kind in (BTN_A, BTN_C):
            app.spotify("previous" if kind == BTN_A else "next")
            return True
        return False


class Calendar(Screen):
    """La semaine d'un coup d'œil, puis les jours qui viennent.

    L'accueil dit aujourd'hui ; cette page dit la suite. En haut la semaine,
    avec un trait sous les jours occupés. Dessous, huit lignes : un jour,
    ses rendez-vous, le jour suivant. La molette fait défiler, B revient à
    aujourd'hui.

    Toutes les lignes ont la même hauteur, titres de jour compris : c'est ce
    qui permet de faire défiler d'un cran sans que rien ne saute.
    """

    NAME = "calendar"
    VISIBLE = 8
    _TOP, _PAS = 114, 22

    def __init__(self):
        self.top = 0
        n = range(self.VISIBLE)
        self._kf = tuple("c.f{}".format(i) for i in n)
        self._kt = tuple("c.t{}".format(i) for i in n)
        self._kd = tuple("c.d{}".format(i) for i in n)
        self._kh = tuple("c.h{}".format(i) for i in n)
        self._kj = tuple("c.j{}".format(i) for i in n)
        self._kx = tuple("c.x{}".format(i) for i in n)
        self._km = tuple("c.m{}".format(i) for i in n)
        self._kl = tuple("c.l{}".format(i) for i in range(7))
        self._kn = tuple("c.n{}".format(i) for i in range(7))
        self._kc = tuple("c.c{}".format(i) for i in range(7))
        self._ka = tuple("c.a{}".format(i) for i in range(7))

    def _lignes(self, st):
        """Les jours et leurs rendez-vous, à plat, dans l'ordre d'affichage."""
        out = []
        for j in st.get("agenda", {}).get("jours") or []:
            out.append((j.get("t", ""), j.get("d", "")))
            for e in j.get("ev") or []:
                out.append(e)
        return out

    def on_turn(self, delta, app):
        reste = max(0, len(self._lignes(app.state)) - self.VISIBLE)
        top = max(0, min(reste, self.top + delta))
        if top != self.top:
            self.top = top
            app.dirty = True

    def on_input(self, ev, app):
        kind, arg = ev
        if kind == BTN_B and arg == SHORT:
            if self.top:
                self.top = 0
                app.dirty = True
            return True
        return False

    def draw(self, c, st, app):
        p = c.p
        ag = st.get("agenda", {})
        _bandeau(c, "CALENDRIER", st, app)

        mois = ag.get("mois", "")
        c.value("c.mois", G, 52, mois, B12, p.HI, str(ag.get("annee", "")),
                B12, p.DIM, 7)
        sem = st.get("jour", {}).get("semaine")
        c.text("c.sem", D, 52, "S{}".format(sem) if sem else "", PX, p.DIM, 1)

        # --- la semaine -----------------------------------------------------
        semaine = ag.get("semaine") or []
        auj = ag.get("auj", -1)
        for i in range(7):
            x = G + 30 * i
            ici = i == auj
            fond = p.FG if ici else p.BG
            lettre, numero, occupe = (semaine[i] if i < len(semaine)
                                      else ("", "", 0))
            c.rrect(self._kc[i], x, 62, 28, 42, 5, fond)
            c.text(self._kl[i], x + 14, 75, lettre, PX,
                   p.BG if ici else p.DIM, 2, 0, fond)
            c.text(self._kn[i], x + 14, 93, str(numero), B9,
                   p.BG if ici else (p.DIM if i > 4 else p.HI), 2, 0, fond)
            c.rect(self._ka[i], x + 12, 97, 4, 2,
                   (p.BG if ici else p.FG) if occupe else fond)
        c.rect("c.filet", G, 112, LARGE, 1, p.RULE)

        # --- les jours qui viennent ----------------------------------------
        lignes = self._lignes(st)
        reste = max(0, len(lignes) - self.VISIBLE)
        if self.top > reste:
            self.top = reste
        for i in range(self.VISIBLE):
            y = self._TOP + self._PAS * i
            k = self.top + i
            gauche = droite = heure = journee = titre = message = ""
            etat, entete = 2, False
            if k < len(lignes):
                l = lignes[k]
                if len(l) == 2:
                    entete = True
                    gauche, droite = l
                else:
                    heure, titre, etat = l[0], l[1], l[2]
                    if not heure:
                        journee = "JOURNEE"
            elif not lignes and i == 0:
                message = ("Rien de prévu" if ag.get("ok", True)
                           else "Agenda indisponible")
            # Une ligne est tantôt un jour, tantôt un rendez-vous, et les
            # deux se dessinent au même endroit. En défilant, ce qui
            # s'efface doit passer AVANT ce qui s'écrit, sinon l'effacement
            # emporte le texte tout juste posé : d'où les deux passes.
            for passe in (True, False):
                if (not gauche) == passe:
                    c.text(self._kt[i], G, y + 15, gauche, PX,
                           p.FG if gauche == "AUJOURD'HUI" else p.DIM)
                if (not droite) == passe:
                    c.text(self._kd[i], D, y + 15, droite, PX, p.DIM, 1)
                if (not heure) == passe:
                    c.text(self._kh[i], G, y + 16, heure, B9,
                           p.FG if etat == 1 else p.HI)
                if (not journee) == passe:
                    c.text(self._kj[i], G, y + 13, journee, PX, p.DIM)
                if (not titre) == passe:
                    c.text(self._kx[i], 72, y + 16, titre, S9, p.HI, 0, 150)
                if i == 0 and (not message) == passe:
                    c.text("c.vide", G, y + 16, message, S9, p.PAST)
            # Un filet au-dessus de chaque jour, sauf en tête de liste où le
            # filet de la semaine fait déjà la séparation.
            c.rect(self._kf[i], G, y + 1, LARGE, 1,
                   p.RULE if entete and i else p.BG)
            c.rect(self._km[i], 8, y + 3, 3, 13, p.FG if etat == 1 else p.BG)

        # L'ascenseur n'apparaît que s'il y a de quoi défiler.
        haut = self._PAS * self.VISIBLE - 4
        if reste:
            taille = max(12, haut * self.VISIBLE // len(lignes))
            c.vbar("c.asc", 231, self._TOP + 2, 2, haut,
                   (haut - taille) * self.top // reste, taille, p.DIM, p.RULE)
        else:
            c.vbar("c.asc", 231, self._TOP + 2, 2, haut, 0, 0, p.DIM, p.BG)

        _pied(c, "SPOTIFY", "ACCUEIL", 2)


# L'ordre du carrousel. Boot n'y figure pas : il ne se voit qu'au démarrage.
CAROUSEL = (Home, Spotify, Calendar)
