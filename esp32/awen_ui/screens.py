"""Les sept écrans d'Awen, aux coordonnées des maquettes.

Chaque écran expose :
    NAME            libellé court, pour la trace série
    draw(g, st)     compose la grille ; ne dessine jamais en pixels directs
    on_input(ev, app)   renvoie True si l'événement a été absorbé

Un écran ne décide rien : il lit `st`, le dernier résumé renvoyé par
/api/esp32/summary, et l'affiche. Les charges, les cibles de répétitions et
les conseils viennent tous du moteur de règles côté serveur — c'est ce qui
garantit que l'écran et l'application web ne racontent jamais deux histoires
différentes.

Texte en ASCII majuscule sans accents : voir grid.py.
"""
from grid import COLS, ROWS
from input import BTN_A, BTN_B, BTN_C, SHORT, LONG, REPEAT, TURN


def _header(g, title, clock):
    g.text(0, 0, title, g.p.HI)
    g.right(0, clock, g.p.DIM)
    g.rule(1)


def _statusbar(g, left, right):
    g.rule(ROWS - 2)
    g.text(0, ROWS - 1, left, g.p.DIM)
    g.right(ROWS - 1, right, g.p.DIM)


class Screen:
    """Base commune. Par défaut un écran n'absorbe rien : la navigation passe."""

    NAME = "?"

    def draw(self, g, st):
        raise NotImplementedError

    def on_input(self, ev, app):
        return False


# --------------------------------------------------------------------------


class Boot(Screen):
    """Amorçage. Les lignes tombent une par une — c'est tout le caractère.

    L'écran se redessine à chaque passage parce que `step` avance ; le
    redessin partiel fait que ça ne coûte qu'une ligne à la fois.
    """

    NAME = "boot"
    CHECKS = ("RESEAU", "SERVEUR", "COACH", "VEILLE EMPLOI", "CAPTEURS")

    def __init__(self):
        self.step = 0

    def draw(self, g, st):
        g.center(2, "A W E N", g.p.HI)
        g.center(3, "assistant personnel", g.p.DIM)
        g.rule(5)
        for i, label in enumerate(self.CHECKS):
            if i > self.step:
                break
            r = 7 + i
            g.text(1, r, label, g.p.DIM)
            done = i < self.step or st.get("ok")
            state = "OK" if done else "..."
            g.text(COLS - 1 - len(state), r, state,
                   g.p.FG if done else g.p.DIM)
        if self.step >= len(self.CHECKS):
            g.text(1, 13, "> demarrage", g.p.FG)
            g.cursor(13, 13, st.get("blink", True))
        _statusbar(g, "v2.4", st.get("ip", ""))


class Home(Screen):
    """Veille. L'heure occupe le tiers haut, tout le reste chuchote."""

    NAME = "home"

    def draw(self, g, st):
        gym = st.get("gym", {})
        g.text(0, 0, st.get("date", "").upper(), g.p.DIM)
        online = st.get("online", True)
        g.right(0, "EN LIGNE" if online else "HORS LIGNE",
                g.p.FG if online else g.p.ALERT)
        g.rule(1)

        # 5 caractères en 16x32 : 80 px, centrés sur 240.
        g.big(10, 3, st.get("time", "--:--"))

        g.rule(7)
        g.text(1, 9, "PROCHAINE SEANCE", g.p.DIM)
        g.text(1, 10, (gym.get("next_focus") or "REPOS").upper(), g.p.HI)
        g.right(10, gym.get("next", ""), g.p.FG)

        g.text(1, 12, "OFFRES DU JOUR", g.p.DIM)
        g.right(12, str(st.get("jobs", {}).get("n", 0)), g.p.HI)

        missed = gym.get("missed", 0)
        g.text(1, 14, "SEANCES RATEES" if missed else "SERIE EN COURS",
               g.p.DIM)
        g.right(14, str(missed) if missed else gym.get("last", ""),
                g.p.ALERT if missed else g.p.FG)

        _statusbar(g, "AWEN", "[OK] MENU")


class Gym(Screen):
    """Séance en cours. Une seule information compte : la série à faire.

    L'encodeur ajuste la charge par pas de 2,5 kg — le plus petit disque de
    la plupart des salles. Chaque cran vaut donc quelque chose de réel.
    """

    NAME = "gym"
    STEP_KG = 2.5

    def __init__(self):
        self.adjust = 0.0        # écart appliqué à la charge programmée

    def draw(self, g, st):
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

        g.text(1, 12, "REPOS", g.p.DIM)
        rest = st.get("rest_s", 0)
        g.text(1, 13, "{:02d}:{:02d}".format(rest // 60, rest % 60), g.p.HI)
        g.bar(8, 13, 20, st.get("rest_pct", 0))

        g.text(1, 15, "FAIT", g.p.DIM)
        g.bar(8, 15, 20, gym.get("done_pct", 0))
        g.right(16, "{} series restantes".format(gym.get("left", 0)), g.p.DIM)

        _statusbar(g, "< PREC", "SUIV >" if not self.adjust else "[OK] GARDER")

    def on_input(self, ev, app):
        kind, arg = ev
        if kind == TURN:
            self.adjust += arg * self.STEP_KG
            app.dirty = True
            return True
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

    def draw(self, g, st):
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

        for i, line in enumerate(c.get("detail", "").split("\n")[:2]):
            g.text(1, 8 + i, line[:28], g.p.DIM)

        g.rule(11)
        if c.get("to_kg") is not None:
            g.text(1, 12, "PROPOSITION", g.p.DIM)
            g.text(1, 13, "{:.1f} KG".format(c.get("from_kg", 0)), g.p.HI)
            g.text(9, 13, "->", g.p.DIM)
            g.text(12, 13, "{:.1f} KG".format(c["to_kg"]), g.p.FG)
            # Pas de jauge de « confiance » ici : le moteur de règles n'en
            # calcule aucune, et afficher un pourcentage inventé donnerait
            # à un chiffre décoratif l'autorité d'une mesure.
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
    """Veille emploi. Trois offres, pas plus : à 30 colonnes il faut trancher."""

    NAME = "jobs"

    def __init__(self):
        self.top = 0

    def draw(self, g, st):
        jobs = st.get("jobs", {})
        offers = jobs.get("offers") or []
        _header(g, "VEILLE EMPLOI", st.get("time", ""))

        n = jobs.get("n", len(offers))
        g.text(1, 3, str(n), g.p.HI)
        g.text(3, 3, "OFFRES CE MATIN" if n else "AUCUNE OFFRE", g.p.FG)

        for i in range(3):
            j = self.top + i
            r = 5 + i * 4
            if j >= len(offers):
                for k in range(3):
                    g.text(0, r + k, " " * COLS)
                continue
            o = offers[j]
            g.text(0, r, ">", g.p.DIM)
            title = o.get("title", "")
            g.text(2, r, title[:26].upper(), g.p.HI)
            g.text(2, r + 1, title[26:52].upper(), g.p.HI)
            # La veille ne note pas les offres : on affiche l'organisme quand
            # le pipeline le fournit, et rien quand il ne le fournit pas.
            g.text(2, r + 2, o.get("org", "")[:28], g.p.DIM)

        more = "v DEFILER" if len(offers) > 3 else ""
        _statusbar(g, "PIPELINE 09:00", more)

    def on_input(self, ev, app):
        kind, arg = ev
        offers = app.state.get("jobs", {}).get("offers") or []
        if len(offers) <= 3:
            return False
        if kind == TURN:
            self.top = max(0, min(len(offers) - 3, self.top + arg))
            app.dirty = True
            return True
        return False


class Settings(Screen):
    """L'écran iconique de TARS, transposé au ton d'Awen.

    Ces pourcentages ne sont pas décoratifs : ils sont renvoyés au serveur et
    modulent la formulation des conseils — jamais les charges, qui restent
    calculées par les règles.
    """

    NAME = "settings"
    KEYS = ("SINCERITE", "HUMOUR", "INSISTANCE", "VERBOSITE")

    def __init__(self):
        self.sel = 1                     # HUMOUR, comme dans le film
        self.values = [95, 75, 60, 40]

    def draw(self, g, st):
        _header(g, "PARAMETRES", st.get("time", ""))
        for i, name in enumerate(self.KEYS):
            r = 4 + i * 3
            focused = i == self.sel
            g.text(1, r, name, g.p.HI if focused else g.p.FG)
            g.right(r, "{:>3}%".format(self.values[i]), g.p.HI)
            g.bar(1, r + 1, 28, self.values[i],
                  g.p.FG if focused else g.p.DIM)
        g.text(1, 17, "> reglage " + self.KEYS[self.sel], g.p.DIM)
        g.cursor(11 + len(self.KEYS[self.sel]), 17, st.get("blink", True))
        _statusbar(g, "^v AJUSTER", "[OK] VALIDER")

    def on_input(self, ev, app):
        kind, arg = ev
        if kind == TURN:
            v = self.values[self.sel] + arg * 5
            self.values[self.sel] = max(0, min(100, v))
            app.dirty = True
            return True
        if kind == BTN_B and arg == SHORT:
            self.sel = (self.sel + 1) % len(self.KEYS)
            app.dirty = True
            return True
        if kind in (BTN_A, BTN_C) and arg == REPEAT:
            step = -5 if kind == BTN_A else 5
            v = self.values[self.sel] + step
            self.values[self.sel] = max(0, min(100, v))
            app.dirty = True
            return True
        return False


class Chat(Screen):
    """La discussion, pour le jour où Awen parlera.

    Le texte s'écrit caractère par caractère : `reveal` est le nombre de
    caractères déjà sortis, avancé par la boucle principale.
    """

    NAME = "chat"

    def __init__(self):
        self.reveal = 0

    def draw(self, g, st):
        chat = st.get("chat", {})
        _header(g, "> AWEN", st.get("time", ""))

        g.text(0, 3, "VOUS", g.p.DIM)
        for i, line in enumerate(_wrap(chat.get("you", ""), COLS)[:2]):
            g.text(0, 4 + i, line, g.p.FG)

        g.text(0, 7, "AWEN", g.p.HI)
        answer = chat.get("awen", "")
        shown = answer[:self.reveal] if self.reveal else answer
        lines = _wrap(shown, COLS)[:5]
        for i, line in enumerate(lines):
            g.text(0, 8 + i, line.ljust(COLS), g.p.FG)
        if lines:
            g.cursor(min(len(lines[-1]), COLS - 1), 8 + len(lines) - 1,
                     st.get("blink", True))

        listening = chat.get("listening")
        _statusbar(g, "* ECOUTE" if listening else "  REPOS", "8B LOCAL")


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


# L'ordre du carrousel. Boot n'y figure pas : il ne se voit qu'au démarrage.
CAROUSEL = (Home, Gym, Coach, Jobs, Settings, Chat)
