"""Les huit écrans d'Awen, aux coordonnées des maquettes.

Chaque écran expose :
    NAME              libellé court, pour la trace série
    draw(g, st, app)  compose la grille ; ne dessine jamais en pixels directs
    on_input(ev, app) renvoie True si l'événement a été absorbé
    on_turn(delta, app)  un cran d'encodeur : delta vaut -1 ou +1

L'ENCODEUR EMET UN DEPLACEMENT

Il n'a pas de position : il dit « un cran vers la droite ». Les écrans
reçoivent donc un ±1 et l'appliquent à ce qu'ils affichent. Rien à
annoncer, rien à rattraper, aucun saut possible en changeant d'écran.

Texte en ASCII majuscule sans accents : voir grid.py.
"""
import time

from grid import COLS, ROWS
from input import BTN_A, BTN_B, BTN_C, SHORT, LONG, REPEAT
import theme


def _header(g, title, st, app):
    """Barre haute : la marque, l'écran, le curseur, l'heure.

    « AWEN » figure partout — c'est le nom de la machine, et un afficheur qui
    ne dit jamais ce qu'il est ressemble à un écran de test.

    C'est le seul mouvement permanent de l'interface. Sans lui un écran
    immobile ne se distingue pas d'un écran gelé — surtout ici, où presque
    rien ne bouge entre deux rafraîchissements espacés de trente secondes.
    Un bloc qui bat une fois par seconde suffit à dire que la machine vit.

    Il ne coûte qu'une cellule par battement, grâce au redessin partiel.
    """
    g.text(0, 0, "AWEN", g.p.FG)
    g.text(5, 0, title, g.p.HI)
    g.cursor(5 + len(title) + 1, 0, st.get("blink", True))
    g.right(0, st.get("time", ""), g.p.DIM)
    _dots(g, app)
    g.rule(1)


def _dots(g, app):
    """Les pastilles de navigation, ligne 1, aux couleurs des ecrans.

    Meme code couleur que la LED : on sait ou l'on est sans lire, et combien
    d'ecrans restent avant de revenir au debut.
    """
    g.dots(1, [theme.rgb565(c) for c in theme.SCREEN_RGB[:len(app.screens)]],
           app.index)


def _statusbar(g, left, right):
    g.rule(ROWS - 2)
    g.text(0, ROWS - 1, left, g.p.DIM)
    g.right(ROWS - 1, right, g.p.DIM)


def _wrap(text, width):
    """Coupe aux espaces, jamais au milieu d'un mot."""
    lines, line = [], ""
    for word in text.split():
        if not line:
            line = word
        elif len(line) + 1 + len(word) <= width:
            line += " " + word
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _mmss(seconds):
    seconds = int(seconds)
    return "{}:{:02d}".format(seconds // 60, seconds % 60)


class Screen:
    """Base commune. Par défaut, un écran n'absorbe rien et ignore la molette."""

    NAME = "?"

    def draw(self, g, st, app):
        raise NotImplementedError

    def on_input(self, ev, app):
        return False

    def on_turn(self, delta, app):
        pass


# --------------------------------------------------------------------------


class Boot(Screen):
    """Amorçage. Les lignes tombent une par une — c'est tout le caractère."""

    NAME = "boot"
    CHECKS = ("RESEAU", "SERVEUR", "COACH", "VEILLE EMPLOI", "SPOTIFY")

    def __init__(self):
        self.step = 0

    def draw(self, g, st, app):
        g.center(2, "A W E N", g.p.HI)
        g.center(3, "assistant personnel", g.p.DIM)
        g.rule(5)
        for i, label in enumerate(self.CHECKS):
            if i > self.step:
                break
            r = 7 + i
            g.text(1, r, label, g.p.DIM)
            done = i < self.step
            state = "OK" if done else "..."
            g.text(COLS - 1 - len(state), r, state,
                   g.p.FG if done else g.p.DIM)
        if self.step >= len(self.CHECKS):
            g.text(1, 13, "> demarrage", g.p.FG)
            g.cursor(13, 13, st.get("blink", True))
        _statusbar(g, "v3.0", st.get("ip", ""))


class Home(Screen):
    """Le tableau de bord. Dense à dessein.

    C'est l'écran qu'on regarde en passant, sans appuyer sur rien : il doit
    répondre aux questions du matin — quel jour, quel temps, tout tourne-t-il,
    y a-t-il des offres — et donner envie d'aller chercher le détail ailleurs.

    Pas de séance ici : elle a son écran, et elle ne se consulte pas d'un
    coup d'œil. La place gagnée sert à ce qui, lui, se lit en une seconde.
    """

    NAME = "home"

    def draw(self, g, st, app):
        jour = st.get("jour", {})
        online = st.get("online", True)

        g.text(0, 0, "AWEN", g.p.FG)
        g.text(5, 0, jour.get("long", st.get("date", ""))[:17], g.p.HI)
        g.right(0, "S{}".format(jour.get("semaine", "")), g.p.DIM)
        _dots(g, app)
        g.rule(1)

        # Ligne 2 laissee VIDE, et c'est la seule facon d'aerer : un glyphe
        # en echelle 4 fait exactement 32 px dans deux lignes de 16, il n'y a
        # aucune marge a prendre dans le trace lui-meme.
        g.big(5, 3, st.get("time", "--:--"), scale=4)
        saint = jour.get("saint", "")
        g.center(5, ("- saint " + saint + " -") if saint else "", g.p.DIM)
        g.rule(6)

        # --- meteo --------------------------------------------------------
        #
        # La police est ASCII, donc pas d'emoji : la couleur fait le travail a
        # leur place, avec un marqueur colore par section.
        m = st.get("meteo", {})
        if m.get("ok"):
            g.text(0, 7, m.get("icon", " "), g.p.HI)
            g.text(2, 7, m.get("label", "")[:16], g.p.FG)
            rain = m.get("rain_pct", 0)
            g.right(7, "pluie {:>3}%".format(rain),
                    g.p.ALERT if rain >= 60 else g.p.DIM)
            # Le gros chiffre sous du texte normal, jamais sous un filet :
            # un filet occupe le dernier pixel de sa ligne et le toucherait.
            g.big(1, 8, "{}C".format(m.get("now_c", 0))[:6], 2)
            g.right(8, "min {:>3}  max {:>3}".format(
                m.get("min_c", 0), m.get("max_c", 0)), g.p.DIM)
        else:
            g.text(1, 7, "METEO INDISPONIBLE", g.p.DIM)

        # --- la piece, juste sous le dehors -------------------------------
        #
        # Les deux cote a cote, c'est tout l'interet : l'API donne la ville,
        # le capteur donne un metre autour de toi, et l'ecart entre les deux
        # est ce qui dit s'il faut ouvrir la fenetre.
        ti, hi = app.sensor.reading(time.ticks_ms())
        g.text(0, 9, "#", g.p.DIM)
        g.text(2, 9, "CHAMBRE", g.p.DIM)
        if ti is None:
            etat = app.sensor.state()
            g.right(9, "pas cable" if etat == "absent" else "muet",
                    g.p.DIM if etat == "absent" else g.p.ALERT)
        else:
            ecart = ti - (m.get("now_c", ti) if m.get("ok") else ti)
            g.right(9, "{:>2}C  {:>2}%  {:+d}".format(ti, hi, ecart),
                    g.p.HI)
        g.rule(10)

        # --- serveur ------------------------------------------------------
        srv = st.get("serveur", {})
        total = srv.get("total", 0)
        ok = srv.get("ok")
        g.text(0, 11, "+" if ok and total else "!",
               g.p.FG if ok and total else g.p.ALERT)
        g.text(2, 11, "SERVEUR", g.p.DIM)
        if not total:
            g.right(11, "PAS DE RELEVE", g.p.ALERT)
        else:
            g.right(11, "{}/{} SERVICES".format(srv.get("up", 0), total),
                    g.p.FG if ok else g.p.ALERT)
            if not ok:
                g.text(2, 12, ("! " + ", ".join(srv.get("down", [])))[:26],
                       g.p.ALERT)
            else:
                g.text(2, 12, "disque {}%  ram {}%  {}".format(
                    srv.get("disk_pct", 0), srv.get("mem_pct", 0),
                    srv.get("uptime", ""))[:27], g.p.DIM)

        # --- ce qui attend une action de ta part -------------------------
        n = st.get("jobs", {}).get("n", 0)
        g.text(0, 13, ">" if n else " ", g.p.HI if n else g.p.DIM)
        g.text(2, 13, "OFFRES DU JOUR", g.p.DIM)
        g.right(13, str(n), g.p.HI if n else g.p.DIM)

        c = st.get("coach", {})
        alert = c.get("level") == "alert"
        g.text(0, 14, c.get("icon") or " ", g.p.ALERT if alert else g.p.FG)
        g.text(2, 14, "COACH", g.p.DIM)
        g.right(14, (c.get("text") or "rien a signaler")[:20],
                g.p.ALERT if alert else g.p.FG)

        sp = st.get("spotify", {})
        playing = sp.get("playing")
        g.text(0, 15, ">" if playing else "|", g.p.FG if playing else g.p.DIM)
        g.text(2, 15, "ECOUTE", g.p.DIM)
        if sp.get("device"):
            g.right(15, "{} - {}".format(sp.get("artist", ""),
                                         sp.get("title", ""))[:20], g.p.FG)
        else:
            g.right(15, "rien", g.p.DIM)
        g.rule(16)

        # --- la liaison, en bas : c'est le moins urgent -------------------
        rssi = app.wifi_rssi()
        g.text(0, 17, "*" if online else "!",
               g.p.FG if online else g.p.ALERT)
        g.text(2, 17, "WIFI", g.p.DIM)
        if rssi is None:
            g.right(17, "EN LIGNE" if online else "HORS LIGNE",
                    g.p.FG if online else g.p.ALERT)
        else:
            # Un dBm ne parle a personne : on le traduit, et on garde le
            # chiffre pour qui veut comparer deux emplacements.
            if rssi >= -60:
                mot, col = "EXCELLENT", g.p.FG
            elif rssi >= -70:
                mot, col = "BON", g.p.FG
            elif rssi >= -80:
                mot, col = "FAIBLE", g.p.HI
            else:
                mot, col = "TRES FAIBLE", g.p.ALERT
            g.right(17, "{} {} dBm".format(mot, rssi), col)
        _statusbar(g, "A/C : ecrans", "B tenu: accueil")


class Gym(Screen):
    """Aperçu de la séance à venir, avec les charges décidées par le coach.

    Volontairement en lecture seule. L'afficheur est posé sur un bureau, pas
    dans la salle : quand tu soulèves, ton téléphone est en main, et une
    série saisie ici n'aurait aucun sens. Ce que tu veux en rentrant, c'est
    savoir ce qui t'attend et à quelle charge.

    La molette fait défiler la liste — cinq exercices tiennent à l'écran.
    """

    NAME = "gym"
    VISIBLE = 5

    def __init__(self):
        self.top = 0

    def _rows(self, st):
        return st.get("gym", {}).get("exercises") or []

    def on_turn(self, delta, app):
        extra = max(0, len(self._rows(app.state)) - self.VISIBLE)
        self.top = max(0, min(extra, self.top + delta))
        app.dirty = True

    def draw(self, g, st, app):
        gym = st.get("gym", {})
        rows = self._rows(st)
        _header(g, "SEANCE {}".format(gym.get("session_no", "--")), st, app)

        focus = (gym.get("focus") or "REPOS").upper()
        g.big(1, 3, focus[:8], 2)
        when = gym.get("today") and "AUJOURD HUI" or gym.get("next", "")
        g.right(3, when, g.p.FG)

        if not rows:
            g.text(1, 6, "AUCUN EXERCICE PROGRAMME", g.p.DIM)
            _statusbar(g, "< PREC", "SUIV >")
            return

        for i in range(self.VISIBLE):
            j = self.top + i
            r = 5 + i * 2
            if j >= len(rows):
                break
            ex = rows[j]
            g.text(0, r, ">", g.p.DIM)
            g.text(2, r, ex.get("name", "").upper(), g.p.HI)
            g.right(r, ex.get("detail", ""), g.p.FG)

        missed = gym.get("missed", 0)
        if missed:
            g.text(1, 16, "{} SEANCE(S) RATEE(S)".format(missed), g.p.ALERT)
        else:
            g.text(1, 16, "dernier : {}".format(gym.get("last", "")), g.p.DIM)

        _statusbar(g, "< PREC", "{}/{}".format(
            self.top + 1, max(1, len(rows) - self.VISIBLE + 1)))


class Coach(Screen):
    """Le conseil du moteur de règles. Deux boutons, pas de troisième voie."""

    NAME = "coach"

    def draw(self, g, st, app):
        c = st.get("coach", {})
        _header(g, "COACH", st, app)

        if not c.get("text"):
            g.text(1, 8, "RIEN A SIGNALER", g.p.DIM)
            g.text(1, 10, "Tes charges sont dans", g.p.DIM)
            g.text(1, 11, "la cible.", g.p.DIM)
            _statusbar(g, "< PREC", "SUIV >")
            return

        level = c.get("level", "info")
        color = g.p.ALERT if level == "alert" else g.p.FG
        g.text(1, 3, ("! " + c.get("text", ""))[:28], color)

        subject = c.get("subject", "")
        g.text(1, 5, subject[:28].upper(), g.p.HI)
        g.text(1, 6, subject[28:56].upper(), g.p.HI)

        # Le serveur envoie deja le motif replie sur deux lignes de 28 : il
        # connait la largeur de l'ecran, autant qu'il fasse la decoupe.
        for i, line in enumerate((c.get("detail") or [])[:2]):
            g.text(1, 8 + i, line, g.p.DIM)

        g.rule(11)
        if c.get("to_kg") is not None:
            g.text(1, 12, "PROPOSITION", g.p.DIM)
            g.text(1, 13, "de {:g} kg a".format(c.get("from_kg", 0)), g.p.DIM)
            # La charge proposee est le seul chiffre qui compte ici : elle
            # merite d'etre lisible depuis l'autre bout du bureau.
            g.big(1, 15, "{:g} KG".format(c["to_kg"]), 2, g.p.HI)
            # Pas de jauge de « confiance » : le moteur de règles n'en calcule
            # aucune, et un pourcentage inventé donnerait à une décoration
            # l'autorité d'une mesure.
            _statusbar(g, "[B] APPLIQUER", "sinon : ignore")
        else:
            g.big(1, 15, "", 2)          # efface une proposition disparue
            _statusbar(g, "< PREC", "SUIV >")

    def on_input(self, ev, app):
        """B applique. Ignorer, c'est simplement passer a l'ecran suivant.

        Pas de bouton « ignorer » : il ne ferait rien de plus que partir, et
        un bouton qui ne fait rien invite a se demander ce qu'il a fait.
        """
        kind, arg = ev
        if kind != BTN_B or arg != SHORT:
            return False
        if app.state.get("coach", {}).get("to_kg") is None:
            return False
        app.apply_advice(True)
        return True


class Jobs(Screen):
    """Veille emploi. Trois offres à l'écran : à 30 colonnes, il faut trancher."""

    NAME = "jobs"

    def __init__(self):
        self.top = 0

    def _offers(self, st):
        return st.get("jobs", {}).get("offers") or []

    def on_turn(self, delta, app):
        extra = max(0, len(self._offers(app.state)) - 3)
        self.top = max(0, min(extra, self.top + delta))
        app.dirty = True

    def draw(self, g, st, app):
        jobs = st.get("jobs", {})
        offers = self._offers(st)
        _header(g, "VEILLE EMPLOI", st, app)

        n = jobs.get("n", len(offers))
        g.text(1, 3, str(n), g.p.HI)
        g.text(3, 3, "OFFRES CE MATIN" if n else "AUCUNE OFFRE", g.p.FG)

        for i in range(3):
            j = self.top + i
            r = 5 + i * 4
            if j >= len(offers):
                continue
            # Le serveur envoie le titre deja replie sur trois lignes de 28.
            # Aucun score de correspondance : la veille n'en calcule pas, et
            # une jauge inventee donnerait a une decoration l'autorite d'une
            # mesure.
            g.text(0, r, ">", g.p.DIM)
            for k, line in enumerate((offers[j].get("title") or [])[:3]):
                g.text(2, r + k, line.upper(), g.p.HI if k == 0 else g.p.DIM)

        _statusbar(g, "PIPELINE 09:00",
                   "{}/{}".format(self.top + 1, max(1, len(offers) - 2))
                   if len(offers) > 3 else "")


class Spotify(Screen):
    """Ce qui joue, et le volume à la molette.

    Un cran vaut deux pour cent : un tour complet couvre toute l'échelle,
    et le geste reste assez fin pour ajuster sans viser.
    """

    NAME = "spotify"

    VOL_STEP = 2                 # % par cran ; un tour couvre l'echelle

    def on_turn(self, delta, app):
        sp = app.state.get("spotify") or {}
        if not sp.get("device"):
            return
        v = max(0, min(100, sp.get("volume", 0) + delta * self.VOL_STEP))
        app.set_volume(v)

    def draw(self, g, st, app):
        sp = st.get("spotify", {})
        _header(g, "> SPOTIFY", st, app)

        if not sp.get("device"):
            g.text(1, 8, "AUCUN APPAREIL", g.p.DIM)
            g.text(1, 10, "Lance une lecture sur", g.p.DIM)
            g.text(1, 11, "ton telephone.", g.p.DIM)
            _statusbar(g, "< PREC", "SUIV >")
            return

        # Le titre en 16x16 : 14 caracteres par ligne, deux lignes. Au-dela
        # on tronque — un titre de chanson se reconnait a son debut.
        # 112 px de cote : 14 colonnes sur 7 lignes, centrees, dans un
        # contour. Sans lui une pochette sombre se fond dans le noir du
        # panneau et on ne voit plus ou elle commence.
        g.frame(7, 3, 16, 9)
        g.image(8, 4, app.cover, app.COVER, sp.get("cover", ""))

        # Le « + [""] » n'est pas une precaution de style : _wrap("") rend une
        # liste vide, et indexer dessus planterait la boucle sur une piste
        # sans titre.
        title = (_wrap(sp.get("title", "").upper(), 14) + [""])[0]
        g.big(1, 13, title[:14], 2)
        g.text(1, 14, sp.get("artist", "")[:28], g.p.FG)

        # Position extrapolee localement : le compteur avance chaque seconde
        # sans que le serveur soit interroge plus souvent. Voir app.py.
        pos = app.play_position()
        dur = sp.get("duration_s", 0)
        g.text(1, 15, _mmss(pos), g.p.DIM)
        g.right(15, _mmss(dur), g.p.DIM)
        g.bar(1, 16, 28, (pos * 100 // dur) if dur else 0)

        # Volume sur une seule ligne : etiquette, jauge et valeur cohabitent
        # sans se toucher, faute de place pour une ligne de plus.
        g.text(0, 17, "VOL", g.p.DIM)
        g.bar(4, 17, 21, sp.get("volume", 0))
        g.right(17, "{:>3}%".format(sp.get("volume", 0)), g.p.HI)

        # 30 colonnes en tout : « [B] PAUSE » tient a gauche, le rappel du
        # geste piste a droite. Le nom de l'appareil ne rentre pas, et il
        # importe moins que de savoir comment sauter une piste.
        _statusbar(g, "[B] " + ("PAUSE" if sp.get("playing") else "LIRE"),
                   "A/C tenu: piste")

    def on_input(self, ev, app):
        """Piste precedente/suivante en MAINTENANT A ou C, pas en tapant.

        L'appui court d'A et de C navigue entre les ecrans, partout et sans
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


class Settings(Screen):
    """L'écran iconique de TARS, transposé au ton d'Awen.

    Ces pourcentages ne sont pas décoratifs : ils modulent la formulation des
    conseils — jamais les charges, qui restent calculées par les règles.
    """

    NAME = "settings"
    KEYS = ("SINCERITE", "HUMOUR", "INSISTANCE", "VERBOSITE")

    def __init__(self):
        self.sel = 1                     # HUMOUR, comme dans le film
        self.values = [95, 75, 60, 40]

    STEP = 5                     # % par cran

    def on_turn(self, delta, app):
        v = self.values[self.sel] + delta * self.STEP
        self.values[self.sel] = max(0, min(100, v))
        app.dirty = True

    def draw(self, g, st, app):
        _header(g, "PARAMETRES", st, app)
        for i, name in enumerate(self.KEYS):
            r = 4 + i * 3
            focused = i == self.sel
            g.text(1, r, name, g.p.HI if focused else g.p.FG)
            # Le curseur marque la ligne que la molette commande. Une simple
            # mise en surbrillance ne suffirait pas : sur cet ecran quatre
            # lignes se ressemblent, et rien d'autre ne bouge.
            if focused:
                g.cursor(1 + len(name) + 1, r, st.get("blink", True))
            g.right(r, "{:>3}%".format(self.values[i]), g.p.HI)
            g.bar(1, r + 1, 28, self.values[i],
                  g.p.FG if focused else g.p.DIM)
        _statusbar(g, "[B] LIGNE", "MOLETTE : VALEUR")

    def on_input(self, ev, app):
        kind, arg = ev
        if kind == BTN_B and arg == SHORT:
            self.sel = (self.sel + 1) % len(self.KEYS)
            app.dirty = True
            return True
        return False


class Theme(Screen):
    """Choix de la palette en deux temps : viser, puis appliquer.

    La molette déplace un curseur dans la liste sans rien changer à
    l'affichage ; B applique la teinte visée et l'enregistre.

    L'aperçu du bas est peint aux couleurs de la teinte VISÉE, pas de la
    teinte active. C'est ce qui permet de garder le geste en deux temps sans
    rien perdre : on juge quand même la couleur avant de s'engager, et
    l'écran entier ne se repeint plus à chaque cran.
    """

    NAME = "theme"

    def __init__(self):
        # La palette active ne se lit qu'à travers app, qui n'existe pas
        # encore ici : le curseur se cale au premier affichage.
        self.sel = None
        self.saved = False

    def _active(self, app):
        for i, p in enumerate(theme.PALETTES):
            if p.name == app.g.p.name:
                return i
        return 0

    def _cursor(self, app):
        if self.sel is None:
            self.sel = self._active(app)
        return self.sel

    def on_turn(self, delta, app):
        self.sel = (self._cursor(app) + delta) % len(theme.PALETTES)
        app.dirty = True

    def draw(self, g, st, app):
        _header(g, "THEME", st, app)

        sel = self._cursor(app)
        actif = self._active(app)
        vise = theme.PALETTES[sel]

        # Le nom en grand prend la couleur qu'il annonce.
        g.big(1, 3, vise.name[:10], 2, vise.HI)
        g.right(3, "{}/{}".format(sel + 1, len(theme.PALETTES)), g.p.DIM)

        for i, p in enumerate(theme.PALETTES):
            r = 5 + i
            ici = i == sel
            g.text(0, r, ">" if ici else " ", g.p.FG)
            g.text(2, r, p.name, g.p.HI if ici else g.p.DIM)
            if ici:
                g.cursor(2 + len(p.name) + 1, r, st.get("blink", True))
            # Sans ce repère, rien ne distinguerait la teinte qu'on vise de
            # celle qui est déjà en place, et B semblerait sans effet.
            if i == actif:
                g.right(r, "ACTIF", g.p.DIM)

        # Les cinq rôles dans les couleurs de la teinte visée : on juge une
        # palette sur pièce, pas sur son nom.
        g.rule(12)
        g.text(1, 13, "APERCU", g.p.DIM)
        g.text(1, 14, "valeur", vise.HI)
        g.text(9, 14, "donnee", vise.FG)
        g.text(17, 14, "etiquette", vise.DIM)
        g.text(1, 15, "alerte", vise.ALERT)
        g.bar(9, 15, 20, 64, vise.FG)

        # Rien n'est affiché quand il n'y a rien de sûr à dire : au démarrage
        # la palette vient bien du fichier, mais l'écran ne l'a pas écrite et
        # n'a donc aucun titre à s'en attribuer le mérite.
        if sel != actif:
            g.text(1, 17, "[B] pour appliquer", g.p.DIM)
        elif self.saved:
            g.text(1, 17, "applique et enregistre", g.p.DIM)

        _statusbar(g, "[B] APPLIQUER", "MOLETTE : CHOIX")

    def on_input(self, ev, app):
        kind, arg = ev
        if kind == BTN_B and arg == SHORT:
            pal = theme.PALETTES[self._cursor(app)]
            # set_palette() vit sur la grille, pas sur l'app : c'est elle qui
            # tient les couleurs et qui doit tout repeindre.
            app.g.set_palette(pal)
            self.saved = theme.save(pal)
            app.dirty = True
            return True
        return False


# L'ordre du carrousel. Boot n'y figure pas : il ne se voit qu'au démarrage.
CAROUSEL = (Home, Gym, Spotify, Coach, Jobs, Settings, Theme)
