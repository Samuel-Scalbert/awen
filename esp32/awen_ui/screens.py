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

        _statusbar(g, "AWEN", "[OK] MENU")


class Gym(Screen):
    """Séance en cours. Une seule information compte : la série à faire.

    Le potard couvre un écart de -10 à +10 kg autour de la charge programmée,
    par pas de 2,5 kg — le plus petit disque de la plupart des salles. Neuf
    positions sur toute la course, donc chaque cran est franc et se retrouve
    au doigt sans regarder.
    """

    NAME = "gym"
    STEP_KG = 2.5
    STEPS = 8                        # 8 intervalles, 9 positions

    def __init__(self):
        self.adjust = 0.0            # écart appliqué à la charge programmée

    def pot_target(self, st):
        half = self.STEPS // 2
        idx = int(self.adjust / self.STEP_KG) + half
        return (idx * 100) // self.STEPS

    def on_pot(self, pct, app):
        half = self.STEPS // 2
        idx = (pct * self.STEPS + 50) // 100
        self.adjust = (idx - half) * self.STEP_KG
        app.dirty = True

    def draw(self, g, st, app):
        gym = st.get("gym", {})
        ex = gym.get("exercise", {})
        _header(g, "{} . SEANCE {}".format(
            (gym.get("today") or "REPOS").upper(),
            gym.get("session_no", "--")), st.get("time", ""))

        g.text(1, 3, ex.get("name", "AUCUN EXERCICE")[:28].upper(), g.p.HI)
        g.text(1, 4, "exercice {} / {}".format(
            ex.get("index", 0), ex.get("count", 0)), g.p.DIM)

        g.frame(0, 6, COLS, 5)
        g.text(2, 7, "SERIE {} / {}".format(
            ex.get("set", 0), ex.get("sets", 0)), g.p.DIM)

        kg = ex.get("weight_kg", 0) + self.adjust
        g.text(2, 8, "{:.1f} KG".format(kg),
               g.p.FG if self.adjust else g.p.HI)
        g.text(COLS - 8, 8, "x {:<3}".format(ex.get("reps", 0)), g.p.FG)
        g.text(2, 9, "cible {} reps".format(ex.get("target", "8-12")), g.p.DIM)

        g.text(1, 11, "REPOS", g.p.DIM)
        rest = st.get("rest_s", 0)
        g.text(1, 12, "{:02d}:{:02d}".format(rest // 60, rest % 60), g.p.HI)
        g.bar(8, 12, 20, st.get("rest_pct", 0))

        g.text(1, 14, "FAIT", g.p.DIM)
        g.bar(8, 14, 20, gym.get("done_pct", 0))
        g.right(15, "{} series restantes".format(gym.get("left", 0)), g.p.DIM)

        _pot_hint(g, 17, app)
        _statusbar(g, "< PREC",
                   "[OK] GARDER" if self.adjust else "SUIV >")

    def on_input(self, ev, app):
        kind, arg = ev
        if kind == BTN_B and arg == SHORT:
            if self.adjust:
                app.commit_weight(self.adjust)
                self.adjust = 0.0
            else:
                app.log_set()
            app.dirty = True
            return True
        return False


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

        for i, line in enumerate(_wrap(c.get("detail", ""), COLS - 2)[:2]):
            g.text(1, 8 + i, line, g.p.DIM)

        g.rule(11)
        if c.get("to_kg") is not None:
            g.text(1, 12, "PROPOSITION", g.p.DIM)
            g.text(1, 13, "{:.1f} KG".format(c.get("from_kg", 0)), g.p.HI)
            g.text(9, 13, "->", g.p.DIM)
            g.text(12, 13, "{:.1f} KG".format(c["to_kg"]), g.p.FG)
            # Pas de jauge de « confiance » : le moteur de règles n'en calcule
            # aucune, et un pourcentage inventé donnerait à une décoration
            # l'autorité d'une mesure.
            for i, line in enumerate(_wrap(c.get("why", ""), COLS - 2)[:2]):
                g.text(1, 15 + i, line, g.p.DIM)
            _statusbar(g, "[A] APPLIQUER", "[B] IGNORER")
        else:
            _statusbar(g, "< PREC", "SUIV >")

    def on_input(self, ev, app):
        kind, arg = ev
        if arg != SHORT:
            return False
        c = app.state.get("coach", {})
        if c.get("to_kg") is None:
            return False
        if kind == BTN_A:
            app.apply_advice(True)
            return True
        if kind == BTN_B:
            app.apply_advice(False)
            return True
        return False


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
            o = offers[j]
            g.text(0, r, ">", g.p.DIM)
            title = o.get("title", "")
            g.text(2, r, title[:26].upper(), g.p.HI)
            g.text(2, r + 1, title[26:52].upper(), g.p.HI)
            # La veille ne note pas les offres : on affiche l'organisme quand
            # le pipeline le fournit, et rien quand il ne le fournit pas.
            g.text(2, r + 2, o.get("org", "")[:28], g.p.DIM)

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
        _statusbar(g, "[A] << [B] {} [C] >>".format("||" if playing else " >"),
                   sp.get("device", "")[:8])

    def on_input(self, ev, app):
        kind, arg = ev
        if arg != SHORT:
            return False
        if kind == BTN_A:
            app.spotify("previous")
            return True
        if kind == BTN_B:
            app.spotify("toggle")
            return True
        if kind == BTN_C:
            app.spotify("next")
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
        _statusbar(g, "[OK] CHOISIR", "POTARD REGLE")

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
