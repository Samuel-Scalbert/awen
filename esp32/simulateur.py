"""Fait tourner le firmware de l'afficheur sur le PC, et rend ses pages en PNG.

    python esp32/simulateur.py [dossier_de_sortie]

CE N'EST PAS UNE MAQUETTE

Ce script n'a aucun dessin à lui. Il importe les modules de esp32/awen_ui/
tels qu'ils partent sur la carte (app.py, screens.py, canvas.py) et leur
fournit ce qu'ils attendent d'un ESP32 : un écran, des broches, un wifi, un
serveur. L'image qui sort est donc celle que la carte produira, au pixel.

Il sert à deux choses : voir une page sans flasher, et VÉRIFIER. Le canevas
ne repeint que ce qui change ; une erreur dans ce calcul laisse des restes à
l'écran, visibles seulement après un certain enchaînement. Le simulateur
rejoue ces enchaînements (la température qui passe de 9 à 10, le
calendrier qu'on fait défiler, Spotify qui s'arrête) et compare chaque fois
l'écran obtenu pas à pas avec le même écran repeint de zéro. Une différence
d'un seul pixel arrête tout.

Ce que le simulateur ne dit pas : la vitesse réelle du bus, et le câblage.
Pour ceux-là il reste `upload.ps1 -Test`, sur la carte.
"""
import copy
import gc
import io
import json
import os
import re
import sys
import tempfile
import time
import types
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

# Les modules du firmware sont importés depuis leur dossier : sans ceci,
# Python y laisserait un __pycache__ que upload.ps1 n'a pas à croiser.
sys.dont_write_bytecode = True

ICI = Path(__file__).resolve().parent
FIRMWARE = ICI / "awen_ui"
W, H = 240, 320

# ---------------------------------------------------------------------------
# Ce qu'un ESP32 fournit, et que le PC n'a pas


class Horloge:
    """Le temps de la carte, que le simulateur fait avancer à la main."""

    ms = 5000

    @classmethod
    def installe(cls):
        time.ticks_ms = lambda: cls.ms
        time.ticks_diff = lambda a, b: a - b
        time.ticks_add = lambda a, b: a + b
        time.sleep_ms = cls.avance
        time.sleep_us = lambda n: None
        gc.mem_free = lambda: 90000

    @classmethod
    def avance(cls, ms):
        cls.ms += int(ms)


class Monde:
    """Ce que les capteurs et le réseau répondent. Les scénarios y touchent."""

    temperature, humidite = 21, 48
    distance_cm = 72
    rssi = -58
    reponse = {}
    en_ligne = True
    posts = []
    urls = []
    cause = 1                   # machine.PWRON_RESET : la carte vient d'être branchée


class Pin:
    IN, OUT, PULL_UP, IRQ_RISING, IRQ_FALLING = 0, 1, 2, 1, 2

    def __init__(self, no, mode=None, pull=None, value=None):
        self.no = no

    def init(self, *a, **k):
        pass

    def value(self, v=None):
        return 1                    # bouton relâché, encodeur au repos

    def irq(self, **k):
        pass


class PWM:
    def __init__(self, pin, freq=1000, duty=0):
        self.d = duty

    def duty(self, v=None):
        if v is not None:
            self.d = v
        return self.d


class WLAN:
    def __init__(self, _if):
        pass

    def active(self, _on):
        pass

    def isconnected(self):
        return True

    def connect(self, *a):
        pass

    def ifconfig(self):
        return ("192.168.1.57", "255.255.255.0", "192.168.1.1", "192.168.1.1")

    def status(self, what):
        return Monde.rssi


class Reponse:
    def __init__(self, corps, code=200):
        self.status_code = code
        self.content = corps
        self.raw = io.BytesIO(corps)

    def json(self):
        return json.loads(self.content)

    def close(self):
        pass


def _get(url, timeout=None):
    if not Monde.en_ligne:
        raise OSError("ECONNABORTED")
    Monde.urls.append(url)
    if "/api/esp32/cover" in url:
        taille = re.search(r"size=(\d+)", url)
        return Reponse(pochette(int(taille.group(1)) if taille else 112))
    return Reponse(json.dumps(Monde.reponse).encode())


def _post(url, json=None, timeout=None):
    Monde.posts.append((url.split("?")[0].rsplit("/", 1)[-1], json))
    return Reponse(b"{}")


class Dht:
    def __init__(self, pin):
        pass

    def measure(self):
        if Monde.temperature is None:
            raise OSError("pas de reponse")

    def temperature(self):
        return Monde.temperature

    def humidity(self):
        return Monde.humidite


def installe_micropython():
    Horloge.installe()
    machine = types.ModuleType("machine")
    machine.Pin, machine.PWM = Pin, PWM
    machine.time_pulse_us = lambda pin, level, timeout: Monde.distance_cm * 58
    machine.disable_irq = lambda: 0
    machine.enable_irq = lambda state: None
    (machine.PWRON_RESET, machine.HARD_RESET, machine.WDT_RESET,
     machine.DEEPSLEEP_RESET, machine.SOFT_RESET) = range(1, 6)
    machine.reset_cause = lambda: Monde.cause
    network = types.ModuleType("network")
    network.WLAN, network.STA_IF = WLAN, 0
    urequests = types.ModuleType("urequests")
    urequests.get, urequests.post = _get, _post
    dht = types.ModuleType("dht")
    dht.DHT11 = dht.DHT22 = Dht
    for nom, mod in (("machine", machine), ("network", network),
                     ("urequests", urequests), ("dht", dht)):
        sys.modules[nom] = mod
    sys.path.insert(0, str(FIRMWARE))


# ---------------------------------------------------------------------------
# L'écran


class Ecran:
    """Le ST7789, réduit à ce que le canevas appelle.

    Comme le vrai, fill_rect reçoit une couleur normale et blit_buffer des
    octets déjà inversés : si le canevas se trompe d'un côté ou de l'autre,
    l'image sort en négatif ici aussi.

    Le bus aussi est là (set_window, cs, dc, spi), pour que la pochette passe
    par le même chemin que sur la carte : les octets s'accumulent pendant
    que CS est bas, et l'image est posée quand il remonte. Un envoi qui ne
    remplit pas exactement la fenêtre échoue, comme il laisserait une bande
    de bruit sur le panneau.
    """

    class _Broche:
        def __init__(self, en_montant=None):
            self.en_montant = en_montant

        def value(self, v=None):
            if v == 1 and self.en_montant:
                self.en_montant()

    class _Bus:
        def __init__(self, ecran):
            self.ecran = ecran

        def write(self, octets):
            self.ecran._flux.extend(octets)

    def __init__(self):
        self.im = Image.new("RGB", (W, H), (255, 0, 255))   # jamais peint
        self.cs = self._Broche(self._fin_envoi)
        self.dc = self._Broche()
        self.spi = self._Bus(self)
        self._fenetre = None
        self._flux = bytearray()
        self.envois = 0

    def set_window(self, x0, y0, x1, y1):
        self._fenetre = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        self._flux = bytearray()

    def _fin_envoi(self):
        if self._fenetre is None:
            return
        x, y, w, h = self._fenetre
        self._fenetre = None
        self.blit_buffer(self._flux, x, y, w, h)

    @staticmethod
    def _rgb(c):
        r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
        return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)

    def fill_rect(self, x, y, w, h, color):
        if w <= 0 or h <= 0:
            return
        assert 0 <= x and 0 <= y and x + w <= W and y + h <= H, \
            "rectangle hors de l'ecran : {} {} {} {}".format(x, y, w, h)
        self.envois += 1
        self.im.paste(self._rgb(color), (x, y, x + w, y + h))

    def blit_buffer(self, buf, x, y, w, h):
        buf = bytes(buf)
        assert len(buf) == w * h * 2, "tampon de {} octets pour {}x{}".format(
            len(buf), w, h)
        assert 0 <= x and 0 <= y and x + w <= W and y + h <= H, \
            "image hors de l'ecran : {} {} {} {}".format(x, y, w, h)
        self.envois += 1
        px = self.im.load()
        k = 0
        for j in range(h):
            for i in range(w):
                px[x + i, y + j] = self._rgb(((buf[k] << 8) | buf[k + 1]) ^ 0xFFFF)
                k += 2

    def draw_image_file(self, path, x, y, w, h):
        with open(path, "rb") as f:
            self.blit_buffer(f.read(), x, y, w, h)


def pochette(cote=112):
    """Une pochette carrée, dans le format que sert /api/esp32/cover."""
    im = Image.new("RGB", (cote, cote), (10, 24, 44))
    d = ImageDraw.Draw(im)
    m = cote // 2
    for part, c in ((0.36, (58, 160, 255)), (0.24, (10, 24, 44)),
                    (0.125, (234, 242, 255)), (0.03, (10, 24, 44))):
        r = int(cote * part)
        d.ellipse((m - r, m - r, m + r, m + r), fill=c)
    out = bytearray()
    brut = im.tobytes()
    for k in range(0, len(brut), 3):
        r, g, b = brut[k], brut[k + 1], brut[k + 2]
        c = (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)) ^ 0xFFFF
        out += bytes((c >> 8, c & 0xFF))
    return bytes(out)


# ---------------------------------------------------------------------------
# Les données d'exemple : celles des maquettes

ETAT = {
    "ok": True, "min": 9 * 60 + 41, "sec": 0,
    "jour": {"long": "Mardi 13 octobre", "semaine": 42},
    "meteo": {"ok": True, "now_c": 18, "min_c": 12, "max_c": 19,
              "rain_pct": 15, "court": "COUVERT"},
    "agenda": {
        "ok": True, "n": 4, "dans": "DANS 1 H 19",
        "jour": [["09:00", "Revue des offres", 0],
                 ["11:00", "Entretien visio", 1],
                 ["14:30", "Dentiste", 2],
                 ["18:30", "Séance : Pull", 2]],
        "jours": [
            {"t": "AUJOURD'HUI", "d": "MAR 13",
             "ev": [["11:00", "Entretien visio", 1], ["14:30", "Dentiste", 2],
                    ["18:30", "Séance : Pull", 2]]},
            {"t": "DEMAIN", "d": "MER 14",
             "ev": [["10:00", "Atelier Data", 2],
                    ["19:00", "Foot avec Tom", 2]]},
            {"t": "JEUDI", "d": "JEU 15",
             "ev": [["", "Salon de l'emploi", 2],
                    ["09:30", "Appel recruteur", 2]]},
            {"t": "VENDREDI", "d": "VEN 16",
             "ev": [["12:30", "Déjeuner équipe", 2]]},
            {"t": "SAMEDI", "d": "SAM 17",
             "ev": [["10:00", "Marché", 2], ["20:00", "Dîner chez Léa", 2]]},
        ],
        "semaine": [["L", 12, 0], ["M", 13, 1], ["M", 14, 1], ["J", 15, 1],
                    ["V", 16, 1], ["S", 17, 1], ["D", 18, 0]],
        "auj": 1, "mois": "Octobre", "annee": 2026,
    },
    "spotify": {"title": "Around the World", "artist": "Daft Punk",
                "album": "Homework", "position_s": 107, "duration_s": 243,
                "volume": 64, "playing": True, "device": "PC",
                "cover": "abc123"},
}


def variante(**changements):
    """ETAT, avec des blocs remplacés : variante(meteo={...})."""
    e = copy.deepcopy(ETAT)
    for cle, valeur in changements.items():
        if isinstance(valeur, dict) and isinstance(e.get(cle), dict):
            e[cle].update(valeur)
        else:
            e[cle] = valeur
    return e


# ---------------------------------------------------------------------------
# La carte, simulée


class Carte:
    """Le firmware complet, démarré sur un écran en mémoire."""

    def __init__(self):
        import app as app_mod
        import input as input_mod
        self.entree = input_mod
        self.travail = tempfile.mkdtemp(prefix="awen-sim-")
        os.chdir(self.travail)                   # réglages enregistrés ici
        app_mod.COVER_FILE = os.path.join(self.travail, "cover.bin")
        self.ecran = Ecran()
        Monde.reponse = copy.deepcopy(ETAT)
        self.app = app_mod.App(self.ecran, {
            "led": {"kind": "rgb", "pin_r": 32, "pin_g": 33, "pin_b": 13},
            "sensor": {"kind": "dht11", "pin": 25},
            "backlight": 22,
            "presence": {"trig": 15, "echo": 34, "threshold_cm": 120,
                         "idle_ms": 600000},
            "ssid": "wifi", "password": "x",
            "base_url": "http://serveur", "api_key": "cle",
            "pins": {"pin_a": 26, "pin_b": 27, "pin_c": 14,
                     "clk": 4, "dt": 19, "pin_push": 16},
        })

    def demarre(self):
        a = self.app
        a.g.wipe()
        en_ligne = a._boot_sequence()
        amorce = self.ecran.im.copy()
        if en_ligne:
            a.fetch()
        a.in_boot = False
        a.g.sweep(0)
        self.images(40)
        return amorce

    def images(self, n=3):
        """Fait tourner la boucle principale n fois."""
        for _ in range(n):
            self.app._tick()

    def recoit(self, etat):
        """Le serveur répond autre chose, et la carte le relève."""
        Monde.reponse = copy.deepcopy(etat)
        self.app.t_poll = 0
        self.images(3)

    def appuie(self, bouton, geste=None):
        self.app.handle((bouton, self.entree.SHORT if geste is None else geste))
        self.images(3)

    def tourne(self, crans):
        for _ in range(abs(crans)):
            self.app.handle((self.entree.TURN, 1 if crans > 0 else -1))
        self.images(3)

    def photo(self):
        return self.ecran.im.copy()

    def repeint(self):
        """Le même écran, repeint de zéro : la référence de toute vérification."""
        a = self.app
        a.g.wipe()
        a.dirty = True
        a.t_spin = Horloge.ms           # le logo ne tourne pas entre les deux
        self.images(1)
        return self.photo()

    def verifie(self, quoi):
        """L'écran obtenu pas à pas doit égaler l'écran repeint de zéro."""
        pas_a_pas = self.photo()
        neuf = self.repeint()
        ecart = ImageChops.difference(pas_a_pas, neuf).getbbox()
        if ecart is not None:
            pas_a_pas.save("ecart-pas-a-pas.png")
            neuf.save("ecart-neuf.png")
            raise AssertionError(
                "{} : l'ecran differe dans la zone {}, images dans {}".format(
                    quoi, ecart, self.travail))
        couleurs = [c for _n, c in neuf.getcolors(W * H)]
        assert (255, 0, 255) not in couleurs, \
            "{} : des pixels n'ont jamais ete peints".format(quoi)


def scenarios(carte):
    """Les enchaînements qui piègent un redessin partiel."""
    e = carte.entree
    faits = []

    def etape(quoi, action=None):
        if action:
            action()
        carte.verifie(quoi)
        faits.append(quoi)

    # --- accueil ------------------------------------------------------------
    etape("accueil, premier affichage")
    etape("une minute passe", lambda: (Horloge.avance(60000), carte.images(3)))
    etape("dehors de 18 a 9 degres",
          lambda: carte.recoit(variante(meteo={"now_c": 9})))
    etape("dehors de 9 a 10 degres",
          lambda: carte.recoit(variante(meteo={"now_c": 10})))
    etape("il gele : -3 dehors, pluie a 100 %", lambda: carte.recoit(variante(
        meteo={"now_c": -3, "min_c": -6, "max_c": 2, "rain_pct": 100,
               "court": "FORTE"})))
    etape("pluie de 100 a 5 %", lambda: carte.recoit(variante(
        meteo={"rain_pct": 5, "court": "CIEL CLAIR"})))
    etape("meteo indisponible",
          lambda: carte.recoit(variante(meteo={"ok": False})))
    etape("meteo revenue", lambda: carte.recoit(ETAT))

    def capteur(t, h):
        Monde.temperature, Monde.humidite = t, h
        Horloge.avance(11000)
        carte.images(3)
    etape("la piece passe a 9 degres", lambda: capteur(9, 100))
    etape("la piece revient a 21", lambda: capteur(21, 48))

    def sonar(cm):
        Monde.distance_cm = cm
        Horloge.avance(1200)
        carte.images(40)
    etape("le sonar ne voit plus personne (235 cm)", lambda: sonar(235))
    etape("le sonar perd l'echo", lambda: sonar(0))
    etape("le sonar revoit quelqu'un a 8 cm", lambda: sonar(8))
    etape("retour a 72 cm", lambda: sonar(72))

    etape("molette : luminosite", lambda: carte.tourne(-1))
    etape("la luminosite s'efface",
          lambda: (Horloge.avance(2500), carte.images(3)))
    carte.tourne(1)                              # on remet 100 %
    Horloge.avance(2500)
    carte.images(3)

    etape("une journee entiere s'ajoute", lambda: carte.recoit(variante(agenda={
        "jour": [["", "Salon de l'emploi", 2], ["11:00", "Entretien visio", 1],
                 ["14:30", "Dentiste", 2]], "dans": "DANS 45 MIN"})))
    etape("la journee entiere devient un horaire", lambda: carte.recoit(variante(
        agenda={"jour": [["08:15", "Petit titre", 0],
                         ["11:00", "Un titre nettement trop long pour la ligne",
                          1]], "dans": "EN COURS"})))
    etape("plus rien de prevu", lambda: carte.recoit(variante(
        agenda={"jour": [], "dans": "", "jours": []})))
    etape("agenda indisponible", lambda: carte.recoit(variante(
        agenda={"ok": False, "jour": [], "dans": "", "jours": []})))
    etape("agenda revenu", lambda: carte.recoit(ETAT))
    etape("deux rendez-vous : le lendemain complete l'accueil",
          lambda: carte.recoit(variante(agenda={
              "jour": [["11:00", "Entretien visio", 1],
                       ["14:30", "Dentiste", 2]]})))
    etape("journee vide : le message, puis le lendemain",
          lambda: carte.recoit(variante(agenda={
              "jour": [], "dans": "", "jours": ETAT["agenda"]["jours"][1:]})))
    etape("le lendemain sans rendez-vous horaires",
          lambda: carte.recoit(variante(agenda={
              "jour": [["11:00", "Entretien visio", 1]],
              "jours": [ETAT["agenda"]["jours"][2]]})))
    etape("quatre rendez-vous : plus de place pour demain",
          lambda: carte.recoit(ETAT))
    etape("la repeinte des dix minutes",
          lambda: (Horloge.avance(600001), carte.images(3)))

    def coupe():
        Monde.en_ligne = False
        carte.app.t_poll = 0
        carte.images(3)
    etape("le serveur ne repond plus", coupe)

    def retablit():
        Monde.en_ligne = True
        carte.app.t_poll = 0
        carte.images(3)
    etape("le serveur revient", retablit)

    # --- le repeint des dix minutes -----------------------------------------
    # Il oublie tout pour repasser chaque élément sur lui-même. S'il tombe
    # sur un relevé qui change l'agenda, l'ancien titre doit disparaître :
    # le 21/10, « Kine » s'écrivait sur « Abonnement volley » sans en
    # effacer la fin.
    a = carte.app
    journee = variante(agenda={"jour": [["", "Abonnement volley youtube", 1]]})
    kine = variante(agenda={"jour": [["13:00", "Kine", 2]]})

    def repeint_et_releve():
        Monde.reponse = copy.deepcopy(kine)
        a.t_poll = 0
        a.t_repaint = Horloge.ms - 600000
        carte.images(3)
    etape("journee entiere", lambda: carte.recoit(journee))
    etape("repeint et nouvel agenda dans la meme image", repeint_et_releve)

    # Le cas courant : l'agenda change pendant une veille de plus de dix
    # minutes, et le repeint tombe au réveil.
    def veille_longue():
        presence = a._update_presence
        a._update_presence = lambda now: None
        a.awake = False
        Monde.reponse = copy.deepcopy(kine)
        a.t_poll = 0
        carte.images(3)
        Horloge.avance(700000)
        a.awake = True
        a.dirty = True
        carte.images(3)
        a._update_presence = presence
    etape("retour a la journee entiere", lambda: carte.recoit(journee))
    etape("veille longue, l'agenda change, reveil", veille_longue)
    etape("agenda d'origine", lambda: carte.recoit(ETAT))

    # --- spotify ------------------------------------------------------------
    etape("page Spotify", lambda: carte.appuie(e.BTN_C))
    assert carte.app.current().NAME == "spotify"
    etape("la piste avance",
          lambda: (Horloge.avance(7000), carte.images(3)))
    etape("volume de 64 a 100", lambda: carte.tourne(18))
    etape("volume de 100 a 8", lambda: carte.tourne(-46))
    Horloge.avance(5000)
    carte.images(3)
    assert ("spotify", {"action": "volume", "value": 8}) in Monde.posts, \
        "le volume n'est pas parti vers le serveur"
    etape("pause", lambda: carte.recoit(variante(
        spotify={"playing": False, "volume": 8})))
    etape("autre piste, titre long a jambages", lambda: carte.recoit(variante(
        spotify={"title": "Gypsy Queen (pour la joie, déjà jouée longuement)",
                 "artist": "Les Négresses Vertes et leurs très nombreux amis",
                 "album": "Trabendo", "position_s": 3, "duration_s": 311,
                 "cover": "def456", "volume": 8})))
    etape("titre court", lambda: carte.recoit(variante(
        spotify={"title": "Été", "artist": "M", "album": "", "position_s": 200,
                 "duration_s": 201, "volume": 8})))
    etape("plus aucun appareil",
          lambda: carte.recoit(variante(spotify={"device": ""})))
    etape("la lecture reprend", lambda: carte.recoit(ETAT))
    n = len(Monde.posts)
    carte.appuie(e.BTN_B)
    carte.appuie(e.BTN_C, e.REPEAT)
    carte.appuie(e.BTN_A, e.REPEAT)
    assert [p[1]["action"] for p in Monde.posts[n:]] == \
        ["toggle", "next", "previous"], Monde.posts[n:]
    assert carte.app.current().NAME == "spotify", \
        "A ou C maintenu a change de page au lieu de changer de piste"

    # --- calendrier ---------------------------------------------------------
    etape("page Calendrier", lambda: carte.appuie(e.BTN_C))
    assert carte.app.current().NAME == "calendar"
    for cran in (1, 2, 3, 4, 5):
        etape("calendrier, molette cran {}".format(cran),
              lambda: carte.tourne(1))
    etape("calendrier, molette en butee", lambda: carte.tourne(9))
    etape("calendrier, on remonte de trois crans", lambda: carte.tourne(-3))
    etape("B revient a aujourd'hui", lambda: carte.appuie(e.BTN_B))
    etape("minuit passe : mercredi", lambda: carte.recoit(variante(agenda={
        "auj": 2, "jours": ETAT["agenda"]["jours"][1:],
        "semaine": [["L", 12, 0], ["M", 13, 0], ["M", 14, 1], ["J", 15, 1],
                    ["V", 16, 1], ["S", 17, 1], ["D", 18, 0]]})))
    etape("mois suivant, nom plus long", lambda: carte.recoit(variante(agenda={
        "mois": "Septembre", "annee": 2027, "auj": 6})))
    etape("mois plus court", lambda: carte.recoit(variante(agenda={
        "mois": "Mai", "annee": 2027, "auj": 0})))
    etape("agenda vide", lambda: carte.recoit(variante(agenda={
        "jour": [], "jours": [], "dans": ""})))
    etape("agenda revenu", lambda: carte.recoit(ETAT))

    # --- le tour complet ----------------------------------------------------
    etape("C ramene a l'accueil", lambda: carte.appuie(e.BTN_C))
    assert carte.app.current().NAME == "home"
    carte.appuie(e.BTN_A)
    assert carte.app.current().NAME == "calendar", "A ne recule pas"
    carte.appuie(e.BTN_B, e.LONG)
    assert carte.app.current().NAME == "home", "B maintenu ne ramene pas"
    etape("accueil, apres le tour complet")

    # --- le journal ---------------------------------------------------------
    journal = [j for nom, j in Monde.posts if nom == "journal"]
    assert [j["evt"] for j in journal] == ["demarrage"], journal
    assert journal[0]["cause"] == "ALIM", journal
    releves = [u for u in Monde.urls if "/api/esp32/pages" in u]
    assert releves and all("&up=" in u and "&mem=" in u and "&p=" in u
                           for u in releves), releves[-1]
    pochettes = [u for u in Monde.urls if "/api/esp32/cover" in u]
    assert pochettes and all("&tag=" in u for u in pochettes), pochettes
    # Une panne qui se répète ne part qu'une fois par minute, au relevé
    # suivant.
    a = carte.app
    n = len(Monde.posts)
    a.note("erreur", "MemoryError (spotify)")
    a.note("erreur", "MemoryError (spotify)")
    a.t_poll = 0
    carte.images(2)
    erreurs = [j for nom, j in Monde.posts[n:] if nom == "journal"]
    assert [j["msg"] for j in erreurs] == ["MemoryError (spotify)"], erreurs
    Horloge.avance(61000)
    a.note("erreur", "OSError 12 (home)")
    a.t_poll = 0
    carte.images(2)
    assert Monde.posts[-1] == ("journal", {
        "evt": "erreur", "msg": "OSError 12 (home)",
        "up": a._up_ms // 1000, "mem": Monde.posts[-1][1]["mem"]}), \
        Monde.posts[-1]
    faits.append("journal : demarrage, etat joint aux releves, erreurs")
    return faits


def planche(pages, sortie, maquettes):
    """Les pages côte à côte, et sous chacune sa maquette si elle existe."""
    k, marge = 2, 24
    lignes = 2 if any(m.exists() for m in maquettes) else 1
    im = Image.new("RGB", (len(pages) * (W * k + marge) + marge,
                           lignes * (H * k + marge) + marge), (28, 28, 30))
    for i, page in enumerate(pages):
        x = marge + i * (W * k + marge)
        im.paste(page.resize((W * k, H * k), Image.NEAREST), (x, marge))
        if maquettes[i].exists():
            m = Image.open(maquettes[i]).convert("RGB")
            im.paste(m.resize((W * k, H * k), Image.NEAREST),
                     (x, marge * 2 + H * k))
    im.save(sortie)


def main():
    sortie = Path(sys.argv[1] if len(sys.argv) > 1 else
                  ICI / "mockups" / "simulateur").resolve()
    sortie.mkdir(parents=True, exist_ok=True)
    installe_micropython()

    carte = Carte()
    amorce = carte.demarre()
    e = carte.entree
    pages = [carte.photo()]
    carte.appuie(e.BTN_C)
    pages.append(carte.photo())
    carte.appuie(e.BTN_C)
    pages.append(carte.photo())
    carte.appuie(e.BTN_C)

    noms = ("1-accueil", "2-spotify", "3-calendrier")
    amorce.resize((W * 3, H * 3), Image.NEAREST).save(sortie / "0-amorcage.png")
    for nom, page in zip(noms, pages):
        page.save(sortie / (nom + "-240x320.png"))
        page.resize((W * 3, H * 3), Image.NEAREST).save(sortie / (nom + ".png"))
    planche(pages, sortie / "planche.png",
            [ICI / "mockups" / "lopaka" / (n + "-240x320.png") for n in noms])
    print("pages rendues dans", sortie)

    faits = scenarios(carte)
    print("{} enchainements verifies : l'ecran pas a pas egale toujours "
          "l'ecran repeint de zero".format(len(faits)))


if __name__ == "__main__":
    main()
