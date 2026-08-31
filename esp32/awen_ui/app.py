"""Navigation, réseau et boucle principale de l'afficheur Awen.

TROIS HORLOGES INDÉPENDANTES, ET C'EST VOLONTAIRE

  - les entrées sont lues à ~60 Hz, sinon un appui semble mou ;
  - l'écran n'est redessiné que si quelque chose a changé (`dirty`), et le
    redessin partiel de grid.py fait qu'une horloge qui avance ne coûte
    qu'une poignée de cellules ;
  - le serveur n'est interrogé que toutes les 30 secondes — sauf sur Spotify,
    où une piste change trop souvent pour attendre autant.

Les mélanger dans une seule cadence est le moyen le plus sûr d'obtenir une
interface qui rame : on redessinerait tout à chaque image, ou on lirait les
boutons une fois par seconde.

LE RATTRAPAGE DU POTENTIOMÈTRE

Un potard a une position physique que le firmware ne peut pas changer. En
passant d'un écran où la valeur est à 75 % à un écran où elle est à 30 %, le
curseur reste à 75 % : appliquer sa position telle quelle écraserait le
volume sans que personne n'ait rien touché.

Le potard ne prend donc la main qu'après avoir traversé la valeur courante,
comme sur une console de mixage. Tant qu'il ne l'a pas rattrapée, l'écran
affiche vers où tourner.
"""
import gc
import time

import network
import urequests

from grid import Grid
from input import BTN_A, BTN_B, BTN_C, Input, LONG, POT, REPEAT, SHORT
import screens
from theme import AMBER as PAL

POLL_MS = 30000          # rafraîchissement des données serveur
POLL_SPOTIFY_MS = 5000   # une piste change trop souvent pour attendre 30 s
FRAME_MS = 16            # lecture des entrées
BLINK_MS = 530           # demi-période du curseur
NET_TIMEOUT = 6          # secondes ; au-delà, on garde l'écran précédent
POT_TOLERANCE = 3        # % d'écart sous lequel le potard reprend la main


class App:
    def __init__(self, display, config):
        self.g = Grid(display, PAL)
        self.io = Input(**config.get("pins", {}))
        self.cfg = config

        self.screens = [cls() for cls in screens.CAROUSEL]
        self.index = 0
        self.boot = screens.Boot()
        self.in_boot = True

        # `online` distingue « pas encore de données » de « serveur injoignable ».
        self.state = {"online": False, "time": "--:--", "ip": "", "blink": True}
        self.dirty = True
        self.t_poll = 0
        self.t_blink = 0

        self.pot_raw = self.io.pot.value() if self.io.pot else 0
        self.pot_target = None
        self.pot_armed = False

    # ------------------------------------------------------------ réseau

    def connect(self):
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            wlan.connect(self.cfg["ssid"], self.cfg["password"])
            deadline = time.ticks_add(time.ticks_ms(), 20000)
            while not wlan.isconnected():
                if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                    return False
                self._boot_tick()
                time.sleep_ms(120)
        self.state["ip"] = wlan.ifconfig()[0]
        return True

    def _url(self, path):
        return "{}{}?key={}".format(self.cfg["base_url"], path,
                                    self.cfg["api_key"])

    def fetch(self):
        """Récupère le résumé. Un échec réseau ne doit jamais vider l'écran.

        On garde les dernières données valides et on bascule seulement le
        témoin « EN LIGNE » : un afficheur qui se vide à la moindre coupure
        wifi est plus inquiétant qu'utile.
        """
        r = None
        try:
            r = urequests.get(self._url("/api/esp32/summary"),
                              timeout=NET_TIMEOUT)
            if r.status_code != 200:
                raise OSError(r.status_code)
            data = r.json()
        except Exception as e:
            print("fetch:", e)
            self.state["online"] = False
            self.dirty = True
            return False
        finally:
            if r is not None:
                r.close()

        data["online"] = True
        data["blink"] = self.state.get("blink", True)
        data["ip"] = self.state.get("ip", "")
        self.state = data
        self.dirty = True
        gc.collect()
        return True

    def _post(self, path, payload):
        r = None
        try:
            r = urequests.post(self._url(path), json=payload,
                               timeout=NET_TIMEOUT)
            return r.status_code == 200
        except Exception as e:
            print("post:", e)
            return False
        finally:
            if r is not None:
                r.close()

    # ------------------------------------------------- actions des écrans

    def commit_weight(self, delta):
        """Le potard a bougé puis B a validé : on remonte l'écart au serveur."""
        if self._post("/api/esp32/weight", {"delta_kg": delta}):
            self.t_poll = 0          # force un rafraîchissement immédiat

    def log_set(self):
        if self._post("/api/esp32/set", {"done": True}):
            self.t_poll = 0

    def apply_advice(self, accept):
        if self._post("/api/esp32/advice", {"accept": accept}):
            self.t_poll = 0

    def spotify(self, action):
        """Lecture, pause, piste suivante — le serveur détient le jeton.

        Rafraîchir Spotify tout de suite après serait inutile : l'API met
        une seconde environ à refléter un changement de piste.
        """
        self._post("/api/esp32/spotify", {"action": action})

    def set_volume(self, pct):
        sp = self.state.get("spotify")
        if sp is not None:
            sp["volume"] = pct       # retour visuel immédiat, sans attendre
            self.dirty = True
        self._post("/api/esp32/spotify", {"action": "volume", "value": pct})

    # -------------------------------------------------------- navigation

    def current(self):
        return self.boot if self.in_boot else self.screens[self.index]

    def rearm_pot(self):
        """Oblige le potard à retraverser la valeur avant de reprendre la main."""
        self.pot_armed = False

    def go(self, step):
        self.index = (self.index + step) % len(self.screens)
        self.rearm_pot()
        self.g.wipe()
        self.dirty = True

    def handle(self, ev):
        if self.in_boot:
            return

        kind, arg = ev

        if kind == POT:
            self.pot_raw = arg
            if self.pot_armed:
                self.current().on_pot(arg, self)
            else:
                self.dirty = True    # le repère de rattrapage doit suivre
            return

        if self.current().on_input(ev, self):
            return                   # l'écran a absorbé l'événement

        if kind == BTN_B and arg == LONG:
            self.index = 0           # retour à l'accueil
            self.rearm_pot()
            self.g.wipe()
            self.dirty = True
        elif kind == BTN_A and arg in (SHORT, REPEAT):
            self.go(-1)
        elif kind == BTN_C and arg in (SHORT, REPEAT):
            self.go(1)

    def _update_pot_arming(self):
        """Le potard reprend la main dès qu'il traverse la valeur courante."""
        target = self.current().pot_target(self.state)
        if target != self.pot_target:
            self.pot_target = target
            self.dirty = True
        if target is None:
            self.pot_armed = False
            return
        if not self.pot_armed and abs(self.pot_raw - target) <= POT_TOLERANCE:
            self.pot_armed = True
            self.dirty = True

    # ------------------------------------------------------------ boucle

    def _boot_tick(self):
        """Fait avancer l'amorçage pendant que le wifi se connecte."""
        self.boot.step = min(self.boot.step + 1, len(self.boot.CHECKS))
        self.g.clear()
        self.boot.draw(self.g, self.state, self)
        self.g.flush()

    def _poll_interval(self):
        return POLL_SPOTIFY_MS if self.current().NAME == "spotify" else POLL_MS

    def run(self):
        self.g.wipe()
        online = self.connect()
        self.boot.step = len(self.boot.CHECKS)
        self._boot_tick()
        if online:
            self.fetch()
        time.sleep_ms(700)              # laisser lire l'écran d'amorçage

        self.in_boot = False
        self.g.wipe()

        while True:
            now = time.ticks_ms()

            for ev in self.io.poll():
                self.handle(ev)

            self._update_pot_arming()

            if time.ticks_diff(now, self.t_blink) >= BLINK_MS:
                self.t_blink = now
                self.state["blink"] = not self.state.get("blink", True)
                self.dirty = True

            if self.t_poll == 0 or \
                    time.ticks_diff(now, self.t_poll) >= self._poll_interval():
                self.t_poll = now
                self.fetch()

            if self.dirty:
                self.dirty = False
                self.g.clear()
                self.current().draw(self.g, self.state, self)
                self.g.flush()

            time.sleep_ms(FRAME_MS)
