"""Les huit écrans d'Awen, aux coordonnées des maquettes.

Chaque écran expose :
    NAME              libellé court, pour la trace série
    draw(g, st, app)  compose la grille ; ne dessine jamais en pixels directs
    on_input(ev, app) renvoie True si l'événement a été absorbé
    pot_target(st)    valeur logique actuelle en %, ou None si l'écran
                      n'utilise pas le potentiomètre
    on_pot(pct, app)  appelé seulement une fois le potard « rattrapé »

LE POTENTIOMÈTRE EST ABSOLU, ET C'EST TOUT LE PROBLÈME

Un encodeur envoie « +1 » ou « -1 » : il n'a pas de position. Un potard, si.
Quand tu quittes les Paramètres avec HUMOUR à 75 % pour aller sur Spotify où
le volume est à 30 %, le curseur est toujours physiquement à 75 %. Sans
précaution, l'écran Spotify collerait le volume à 75 % à la première lecture,
sans que tu aies rien touché.

La parade est celle des consoles de mixage : le potard ne prend la main
qu'après être passé par la valeur courante. Tant qu'il ne l'a pas rattrapée,
l'écran affiche vers où tourner. C'est App qui arbitre (voir app.py), les
écrans se contentent de déclarer leur valeur via pot_target().

Texte en ASCII majuscule sans accents : voir grid.py.
"""
from grid import COLS, ROWS
from input import BTN_A, BTN_B, BTN_C, POT, SHORT, LONG, REPEAT


def _header(g, title, clock):
    g.text(0, 0, title, g.p.HI)
    g.right(0, clock, g.p.DIM)
    g.rule(1)


def _statusbar(g, left, right):
    g.rule(ROWS - 2)
    g.text(0, ROWS - 1, left, g.p.DIM)
    g.right(ROWS - 1, right, g.p.DIM)


def _pot_hint(g, row, app):
    """Affiche vers où tourner tant que le potard n'a pas rattrapé la valeur.

    Sans ce repère, l'utilisateur tourne et ne voit rien bouger : il croit le
    potard cassé alors qu'il est simplement en attente de rattrapage.
    """
    if app.pot_armed or app.pot_target is None:
        return
    arrow = "TOURNE >" if app.pot_raw < app.pot_target else "< TOURNE"
    g.text(1, row, "{} {:>3}%".format(arrow, app.pot_target), g.p.DIM)


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
    """Base commune. Par défaut, un écran n'absorbe rien et ignore le potard."""

    NAME = "?"

    def draw(self, g, st, app):
        raise NotImplementedError

    def on_input(self, ev, app):
        return False

    def pot_target(self, st):
        return None

    def on_pot(self, pct, app):
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
    """Veille. L'heure occupe le tiers haut, tout le reste chuchote."""

    NAME = "home"

    def draw(self, g, st, app):
        gym = st.get("gym", {})
        g.text(0, 0, st.get("date", "").upper(), g.p.DIM)
        online = st.get("online", True)
        g.right(0, "EN LIGNE" if online else "HORS LIGNE",
                g.p.FG if online else g.p.ALERT)
        g.rule(1)

        # 5 caractères en 32x32 (echelle 4) : 160 px, centrés sur 240.
        g.big(5, 3, st.get("time", "--:--"), scale=4)

        g.rule(7)
        g.text(1, 9, "PROCHAINE SEANCE", g.p.DIM)
        g.text(1, 10, (gym.get("next_focus") or "REPOS").upper(), g.p.HI)
        g.right(10, gym.get("next", ""), g.p.FG)

        g.text(1, 12, "OFFRES DU JOUR", g.p.DIM)
        g.right(12, str(st.get("jobs", {}).get("n", 0)), g.p.HI)

        # Étiquette courte : à 30 colonnes, « DERNIERE SEANCE » plus une date
        # alignée à droite se touchent sans espace.
        missed = gym.get("missed", 0)
        g.text(1, 14, "RATEES" if missed else "DERNIERE", g.p.DIM)
        g.right(14, str(missed) if missed else gym.get("last", ""),
                g.p.ALERT if missed else g.p.FG)

        # Pas de « [OK] MENU » : B ne fait rien ici, et annoncer une action
        # inexistante est pire que de n'en annoncer aucune.
        _statusbar(g, "AWEN", "A/C : ecrans")


class Gym(Screen):
    """Aperçu de la séance à venir, avec les charges décidées par le coach.

    Volontairement en lecture seule. L'afficheur est posé sur un bureau, pas
    dans la salle : quand tu soulèves, ton téléphone est en main, et une
    série saisie ici n'aurait aucun sens. Ce que tu veux en rentrant, c'est
    savoir ce qui t'attend et à quelle charge.

    Le potard fait défiler la liste — cinq exercices tiennent à l'écran.
    """

    NAME = "gym"
    VISIBLE = 5

    def __init__(self):
        self.top = 0

    def _rows(self, st):
        return st.get("gym", {}).get("exercises") or []

    def pot_target(self, st):
        extra = max(0, len(self._rows(st)) - self.VISIBLE)
        return (self.top * 100) // extra if extra else None

    def on_pot(self, pct, app):
        extra = max(0, len(self._rows(app.state)) - self.VISIBLE)
        if extra:
            self.top = (pct * extra + 50) // 100
            app.dirty = True

    def draw(self, g, st, app):
        gym = st.get("gym", {})
        rows = self._rows(st)
        _header(g, "SEANCE {}".format(gym.get("session_no", "--")),
                st.get("time", ""))

        focus = (gym.get("focus") or "REPOS").upper()
        g.text(1, 3, focus, g.p.HI)
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

        _pot_hint(g, 17, app)
        _statusbar(g, "< PREC", "{}/{}".format(
            self.top + 1, max(1, len(rows) - self.VISIBLE + 1)))


class Coach(Screen):
    """Le conseil du moteur de règles. Deux boutons, pas de troisième voie."""

    NAME = "coach"

    def draw(self, g, st, app):
        c = st.get("coach", {})
        _header(g, "COACH", st.get("time", ""))

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
            g.text(1, 13, "PROPOSITION", g.p.DIM)
            g.text(1, 15, "{:g} KG".format(c.get("from_kg", 0)), g.p.HI)
            g.text(9, 15, "->", g.p.DIM)
            g.text(12, 15, "{:g} KG".format(c["to_kg"]), g.p.FG)
            # Pas de jauge de « confiance » : le moteur de règles n'en calcule
            # aucune, et un pourcentage inventé donnerait à une décoration
            # l'autorité d'une mesure.
            _statusbar(g, "[B] APPLIQUER", "sinon : ignore")
        else:
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

    def pot_target(self, st):
        extra = max(0, len(self._offers(st)) - 3)
        if not extra:
            return None
        return (self.top * 100) // extra

    def on_pot(self, pct, app):
        extra = max(0, len(self._offers(app.state)) - 3)
        if extra:
            self.top = (pct * extra + 50) // 100
            app.dirty = True

    def draw(self, g, st, app):
        jobs = st.get("jobs", {})
        offers = self._offers(st)
        _header(g, "VEILLE EMPLOI", st.get("time", ""))

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

        _pot_hint(g, 17, app)
        _statusbar(g, "PIPELINE 09:00",
                   "{}/{}".format(self.top + 1, max(1, len(offers) - 2))
                   if len(offers) > 3 else "")


class Spotify(Screen):
    """Ce qui joue, et le volume au potard.

    C'est l'usage le plus naturel d'un potentiomètre de tout le firmware : un
    volume a une position absolue, exactement comme le curseur. Là où un
    encodeur oblige à tourner longtemps depuis une valeur inconnue, le potard
    donne le volume au premier coup d'œil, sans rien afficher.
    """

    NAME = "spotify"

    def pot_target(self, st):
        sp = st.get("spotify", {})
        if not sp.get("device"):
            return None
        return sp.get("volume", 50)

    def on_pot(self, pct, app):
        app.set_volume(pct)

    def draw(self, g, st, app):
        sp = st.get("spotify", {})
        _header(g, "> SPOTIFY", st.get("time", ""))

        if not sp.get("device"):
            g.text(1, 8, "AUCUN APPAREIL", g.p.DIM)
            g.text(1, 10, "Lance une lecture sur", g.p.DIM)
            g.text(1, 11, "ton telephone.", g.p.DIM)
            _statusbar(g, "< PREC", "SUIV >")
            return

        for i, line in enumerate(_wrap(sp.get("title", ""), COLS - 2)[:2]):
            g.text(1, 3 + i, line.upper(), g.p.HI)
        g.text(1, 6, sp.get("artist", "")[:28], g.p.FG)
        g.text(1, 7, sp.get("album", "")[:28], g.p.DIM)

        pos = sp.get("position_s", 0)
        dur = sp.get("duration_s", 0)
        g.text(1, 10, _mmss(pos), g.p.DIM)
        g.right(10, _mmss(dur), g.p.DIM)
        g.bar(1, 11, 28, (pos * 100 // dur) if dur else 0)

        g.text(1, 14, "VOLUME", g.p.DIM)
        g.right(14, "{:>3}%".format(sp.get("volume", 0)), g.p.HI)
        g.bar(1, 15, 28, sp.get("volume", 0))

        _pot_hint(g, 17, app)
        playing = sp.get("playing")
        # 30 colonnes en tout : « [B] PAUSE » tient a gauche, le rappel du
        # geste piste a droite. Le nom de l'appareil ne rentre pas, et il
        # importe moins que de savoir comment sauter une piste.
        _statusbar(g, "[B] " + ("PAUSE" if playing else "LIRE"),
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

    def pot_target(self, st):
        return self.values[self.sel]

    def on_pot(self, pct, app):
        self.values[self.sel] = pct
        app.dirty = True

    def draw(self, g, st, app):
        _header(g, "PARAMETRES", st.get("time", ""))
        for i, name in enumerate(self.KEYS):
            r = 4 + i * 3
            focused = i == self.sel
            g.text(1, r, name, g.p.HI if focused else g.p.FG)
            g.right(r, "{:>3}%".format(self.values[i]), g.p.HI)
            g.bar(1, r + 1, 28, self.values[i],
                  g.p.FG if focused else g.p.DIM)
        _pot_hint(g, 17, app)
        _statusbar(g, "[B] LIGNE SUIV", "POTARD : VALEUR")

    def on_input(self, ev, app):
        kind, arg = ev
        if kind == BTN_B and arg == SHORT:
            self.sel = (self.sel + 1) % len(self.KEYS)
            app.rearm_pot()          # nouvelle valeur : il faut la rattraper
            app.dirty = True
            return True
        return False


# L'ordre du carrousel. Boot n'y figure pas : il ne se voit qu'au démarrage.
CAROUSEL = (Home, Gym, Spotify, Coach, Jobs, Settings)
