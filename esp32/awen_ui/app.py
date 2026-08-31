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
import theme

POLL_MS = 30000          # rafraîchissement des données serveur
POLL_SPOTIFY_MS = 5000   # une piste change trop souvent pour attendre 30 s
FRAME_MS = 16            # lecture des entrées
BLINK_MS = 530           # demi-période du curseur
NET_TIMEOUT = 6          # secondes ; au-delà, on garde l'écran précédent
POT_TOLERANCE = 3        # % d'écart sous lequel le potard reprend la main
COVER = 64               # côté de la pochette, doit égaler COVER_SIZE serveur

# Rythme des animations. Ces valeurs se lisent, elles ne s'expédient pas :
# une ligne d'amorçage qui apparaît en 120 ms n'est pas une animation, c'est
# un clignotement. 300 ms laisse le temps de suivre la liste qui se remplit.
BOOT_STEP_MS = 300       # apparition d'une ligne d'amorçage
BOOT_HOLD_MS = 900       # pause finale, pour lire l'écran complet
SWEEP_MS = 14            # une ligne du balayage de transition

# Temps d'immobilité du potard avant d'envoyer le volume. Chaque envoi est
# une requête HTTP bloquante vers le serveur, qui en fait une autre vers
# Spotify : en tirer une par cran ferait une centaine d'appels sur une seule
# rotation, tous mis à la queue leu leu pendant que l'écran attend. On
# n'envoie donc que la valeur finale, une fois le geste terminé.
VOLUME_SETTLE_MS = 250

# Chien de garde matériel : la boucle doit le nourrir plus souvent que ça,
# sinon la carte redémarre. Large, parce qu'une requête HTTP lente peut
# légitimement immobiliser la boucle six secondes.
WDT_MS = 60000
MEM_WARN = 20000         # octets libres sous lesquels on s'inquiète


class App:
    COVER = COVER

    def __init__(self, display, config):
        self.g = Grid(display, theme.load())
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
        self.wlan = None
        self._vol_pending = None
        self._vol_at = 0
        self._vol_local = 0
        self._vol_hold = 0          # jusqu'à quand la valeur locale prime
        self.cover = None           # pochette en RGB565 brut
        self._cover_tag = None

    # ------------------------------------------------------------ réseau

    def connect(self):
        """Lance la connexion sans attendre : l'amorçage l'anime par-dessus."""
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        if not self.wlan.isconnected():
            self.wlan.connect(self.cfg["ssid"], self.cfg["password"])
        return self.wlan

    def _wifi_ok(self):
        if self.wlan is not None and self.wlan.isconnected():
            self.state["ip"] = self.wlan.ifconfig()[0]
            return True
        return False

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

        # Spotify met une seconde ou deux à refléter un changement de volume.
        # Sans ce garde-fou, un rafraîchissement qui tombe pendant qu'on
        # tourne ramènerait la jauge à l'ancienne valeur, et le potard
        # semblerait lutter contre l'écran.
        if time.ticks_diff(self._vol_hold, time.ticks_ms()) > 0:
            sp = data.get("spotify")
            if isinstance(sp, dict):
                sp["volume"] = self._vol_local

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

    def apply_advice(self, accept):
        if self._post("/api/esp32/advice", {"accept": accept}):
            self.t_poll = 0

    def fetch_cover(self, tag):
        """Récupère la pochette réduite, seulement quand elle a changé.

        Le serveur la renvoie déjà en 64x64 RGB565 inversé : l'ESP32 n'a plus
        qu'à la pousser sur le bus SPI. Décoder un JPEG ici serait hors de
        portée, et redemander 8 Ko toutes les cinq secondes pour la même
        image serait du gaspillage pur.
        """
        if tag == self._cover_tag:
            return
        self._cover_tag = tag
        if not tag:
            self.cover = None
            return
        r = None
        try:
            r = urequests.get(self._url("/api/esp32/cover"), timeout=NET_TIMEOUT)
            if r.status_code != 200:
                raise OSError(r.status_code)
            data = r.content
        except Exception as e:
            print("cover:", e)
            self.cover = None
            self._cover_tag = None      # on retentera au prochain passage
            return
        finally:
            if r is not None:
                r.close()
        self.cover = data if len(data) == self.COVER * self.COVER * 2 else None
        self.dirty = True
        gc.collect()

    def spotify(self, action):
        """Lecture, pause, piste suivante — le serveur détient le jeton.

        Rafraîchir Spotify tout de suite après serait inutile : l'API met
        une seconde environ à refléter un changement de piste.
        """
        self._post("/api/esp32/spotify", {"action": action})

    def set_volume(self, pct):
        """Affiche tout de suite, envoie quand le geste s'arrête.

        La jauge suit le doigt sans latence parce qu'elle est mise à jour
        localement ; seul le réseau attend. C'est ce découplage qui rend le
        réglage fluide au lieu de saccadé.
        """
        sp = self.state.get("spotify")
        if sp is not None:
            sp["volume"] = pct
            self.dirty = True
        self._vol_pending = pct
        self._vol_local = pct
        self._vol_at = time.ticks_ms()
        self._vol_hold = time.ticks_add(self._vol_at, 4000)

    def _flush_volume(self, now):
        if self._vol_pending is None:
            return
        if time.ticks_diff(now, self._vol_at) < VOLUME_SETTLE_MS:
            return
        pct, self._vol_pending = self._vol_pending, None
        self._post("/api/esp32/spotify", {"action": "volume", "value": pct})

    # -------------------------------------------------------- navigation

    def current(self):
        return self.boot if self.in_boot else self.screens[self.index]

    def rearm_pot(self):
        """Oblige le potard à retraverser la valeur avant de reprendre la main."""
        self.pot_armed = False

    def set_palette(self, palette):
        """Change de teinte à chaud, depuis l'écran Theme."""
        self.g.set_palette(palette)
        self.dirty = True

    def go(self, step):
        self.index = (self.index + step) % len(self.screens)
        self.rearm_pot()
        self.g.sweep(SWEEP_MS)       # au lieu d'un flash noir
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
            self.g.sweep(SWEEP_MS)
            self.dirty = True
        elif kind == BTN_A and arg in (SHORT, REPEAT):
            self.go(-1)
        elif kind == BTN_C and arg in (SHORT, REPEAT):
            self.go(1)

    def _update_pot_arming(self):
        """Le potard reprend la main dès qu'il traverse la valeur courante."""
        screen = self.current()
        # Un encodeur n'a rien à rattraper : il est relatif par nature.
        if not self.io.absolute or screen.POT_FREE:
            # Écran qui parcourt une liste : il n'y a aucune valeur à écraser
            # par accident, donc pas de rattrapage. Sans ce cas, un
            # pot_target() à None désarmerait le potard et l'écran ne
            # recevrait plus rien — c'est ce qui empêchait de changer de thème.
            self.pot_armed = True
            if self.pot_target is not None:
                self.pot_target = None
                self.dirty = True
            return

        target = screen.pot_target(self.state)
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

    def _boot_draw(self):
        self.g.clear()
        self.boot.draw(self.g, self.state, self)
        self.g.flush()

    def _boot_sequence(self):
        """Révèle les lignes d'amorçage une par une, à cadence fixe.

        La version précédente n'animait que pendant l'attente du wifi : quand
        la connexion était déjà établie, les cinq lignes apparaissaient d'un
        seul coup et l'écran semblait figé. Le rythme ne doit rien devoir au
        réseau — c'est une animation, pas une barre de progression.

        La connexion se poursuit pendant ce temps ; on la relève à la fin.
        """
        self.connect()
        deadline = time.ticks_add(time.ticks_ms(), 20000)

        for step in range(len(self.boot.CHECKS) + 1):
            self.boot.step = step
            self._boot_draw()
            time.sleep_ms(BOOT_STEP_MS)

        # Toutes les lignes sont affichées : on laisse au wifi le temps qui
        # lui reste, sans figer l'ecran — le curseur continue de clignoter.
        while not self._wifi_ok():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                return False
            self.state["blink"] = not self.state.get("blink", True)
            self._boot_draw()
            time.sleep_ms(BLINK_MS)
        return True

    def _poll_interval(self):
        return POLL_SPOTIFY_MS if self.current().NAME == "spotify" else POLL_MS

    def run(self):
        self.g.wipe()
        online = self._boot_sequence()
        if online:
            self.fetch()
        time.sleep_ms(BOOT_HOLD_MS)     # laisser lire l'écran complet

        self.in_boot = False
        self.g.sweep(SWEEP_MS)          # on entre dans l'interface

        # Chien de garde matériel : si la boucle cesse de le nourrir pendant
        # une minute, la carte redémarre. C'est le seul recours contre un
        # blocage dur — un socket qui ne rend jamais la main, le bus SPI qui
        # se fige — que l'attrapage d'exceptions ne peut pas couvrir.
        wdt = None
        try:
            from machine import WDT
            wdt = WDT(timeout=WDT_MS)
        except Exception as e:
            print("wdt indisponible:", e)

        while True:
            if wdt is not None:
                wdt.feed()
            try:
                self._tick()
            except Exception as e:
                # Sans ce filet, la moindre exception tue run() et l'écran
                # reste figé sur sa dernière image : ça ressemble à un gel,
                # mais le programme n'existe plus. Une panne passagère ne doit
                # pas coûter l'afficheur jusqu'au prochain débranchement.
                print("boucle:", e)
                gc.collect()
                time.sleep_ms(500)

    def _tick(self):
        """Une image. Tout ce qui peut échouer est appelé depuis ici.

        Découpé de run() pour qu'une exception soit rattrapée sans tuer la
        boucle : la panne coûte une image, pas l'afficheur.
        """
        now = time.ticks_ms()

        for ev in self.io.poll():
            self.handle(ev)

        self._update_pot_arming()
        self._flush_volume(now)

        if time.ticks_diff(now, self.t_blink) >= BLINK_MS:
            self.t_blink = now
            self.state["blink"] = not self.state.get("blink", True)
            self.dirty = True

        if self.t_poll == 0 or                 time.ticks_diff(now, self.t_poll) >= self._poll_interval():
            self.t_poll = now
            self._ensure_wifi()
            self.fetch()
            # Uniquement sur l'ecran concerne : telecharger 8 Ko pour une
            # image que personne ne regarde n'aurait aucun sens.
            if self.current().NAME == "spotify":
                self.fetch_cover(self.state.get("spotify", {}).get("cover", ""))
            self._watch_memory()

        if self.dirty:
            self.dirty = False
            self.g.clear()
            self.current().draw(self.g, self.state, self)
            self.g.flush()

        time.sleep_ms(FRAME_MS)

    def _ensure_wifi(self):
        """Relance la connexion si elle est tombée.

        Une box qui redémarre, un canal qui change, et la carte reste
        déconnectée pour toujours : rien dans le firmware ne retentait, et
        l'écran affichait « HORS LIGNE » jusqu'au débranchement.
        """
        if self.wlan is None or self.wlan.isconnected():
            return
        try:
            self.wlan.connect(self.cfg["ssid"], self.cfg["password"])
        except Exception as e:
            print("wifi:", e)

    def _watch_memory(self):
        """Compacte et signale la mémoire libre.

        MicroPython libère mais ne compacte pas : les allocations répétées
        (le JSON à chaque cycle, 8 Ko par pochette) morcellent le tas jusqu'à
        ce qu'une allocation échoue, après des heures et jamais tout de
        suite. Le chiffre part sur la console série, c'est lui qu'il faudra
        regarder si les gels reviennent.
        """
        gc.collect()
        free = gc.mem_free()
        if free < MEM_WARN:
            print("memoire libre basse :", free)
