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

LA MOLETTE ENVOIE UN DÉPLACEMENT

Un TURN vaut ±1 cran, jamais une valeur absolue : l'écran courant l'ajoute
à ce qu'il affiche. Rien ne saute en changeant d'écran, et il n'y a donc
aucun mécanisme de rattrapage ici. Le pourquoi est dans input.py.
"""
import gc
import time

import network
import urequests

from grid import Grid
from input import BTN_A, BTN_B, BTN_C, Input, LONG, REPEAT, SHORT, TURN
import led as led_mod
import screens
import sensor as sensor_mod
import theme

POLL_MS = 30000          # rafraîchissement des données serveur
POLL_SPOTIFY_MS = 5000   # une piste change trop souvent pour attendre 30 s
# Apres un echec, on retente vite : attendre le cycle complet laisserait
# l'ecran affirmer « HORS LIGNE » une demi-minute pour une socket avortee.
RETRY_MS = 4000
FRAME_MS = 16            # lecture des entrées
BLINK_MS = 530           # demi-période du curseur
NET_TIMEOUT = 6          # secondes ; au-delà, on garde l'écran précédent
COVER = 112              # côté de la pochette, doit égaler COVER_SIZE serveur
COVER_FILE = "/cover.bin"   # 25 Ko : sur la flash, jamais en RAM

# Rythme des animations. Ces valeurs se lisent, elles ne s'expédient pas :
# une ligne d'amorçage qui apparaît en 120 ms n'est pas une animation, c'est
# un clignotement. 300 ms laisse le temps de suivre la liste qui se remplit.
BOOT_STEP_MS = 300       # apparition d'une ligne d'amorçage
BOOT_HOLD_MS = 900       # pause finale, pour lire l'écran complet
SWEEP_MS = 14            # une ligne du balayage de transition

# Temps d'immobilité de la molette avant d'envoyer le volume. Chaque envoi est
# une requête HTTP bloquante vers le serveur, qui en fait une autre vers
# Spotify : en tirer une par cran ferait une centaine d'appels sur une seule
# rotation, tous mis à la queue leu leu pendant que l'écran attend. On
# n'envoie donc que la valeur finale, une fois le geste terminé.
VOLUME_SETTLE_MS = 250

MEM_WARN = 20000         # octets libres sous lesquels on s'inquiète

# PAS DE machine.WDT ICI, ET C'EST DELIBERE
#
# On en avait mis un. Il a redémarré la carte en pleine opération légitime :
# sur ESP32, machine.WDT s'appuie sur le chien de garde de tâches de
# l'ESP-IDF, dont la fenêtre globale est bien plus courte que le délai qu'on
# croit demander. Le journal disait « mpy_machine_wdt did not reset in time »
# alors que la boucle tournait normalement.
#
# Le filet à exceptions ci-dessous couvre le vrai besoin — une panne coûte
# une image, pas l'afficheur — sans rebooter à contretemps.


class App:
    COVER = COVER

    def __init__(self, display, config):
        self.g = Grid(display, theme.load())
        self.io = Input(**config.get("pins", {}))
        self.led = led_mod.make(**config.get("led", {}))
        self.sensor = sensor_mod.make(**config.get("sensor", {}))
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

        self.wlan = None
        self._vol_pending = None
        self._vol_at = 0
        self._vol_local = 0
        self._vol_hold = 0          # jusqu'à quand la valeur locale prime
        self.cover = None           # pochette en RGB565 brut
        self._cover_tag = None
        self._pos_at = 0            # quand la position de lecture a été lue

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

    def wifi_rssi(self):
        """Puissance du signal en dBm, ou None si indisponible.

        LE isconnected() N'EST PAS UNE POLITESSE

        Interroger status('rssi') sur une interface qui n'est pas associée
        descend dans esp_wifi_sta_get_ap_info(), et selon l'état de la pile
        celle-ci appelle abort() au niveau ESP-IDF. Ce n'est pas une
        exception Python : aucun try/except ne la rattrape, le programme
        meurt et la carte redémarre — c'est exactement le
        « abort() was called on core 1 » qu'on voyait au premier affichage.
        """
        w = self.wlan
        if w is None or not w.isconnected():
            return None
        try:
            return w.status("rssi")
        except Exception:
            return None

    def _url(self, path):
        return "{}{}?key={}".format(self.cfg["base_url"], path,
                                    self.cfg["api_key"])

    def fetch(self):
        """Récupère le résumé. Un échec réseau ne doit jamais vider l'écran.

        On garde les dernières données valides et on bascule seulement le
        témoin « EN LIGNE » : un afficheur qui se vide à la moindre coupure
        wifi est plus inquiétant qu'utile.
        """
        # Le ramasse-miettes AVANT la requete, pas apres : lwip alloue ses
        # tampons au moment de la connexion, et c'est precisement la qu'il
        # lui faut de la place. Un tas fragmente donne un ECONNABORTED qui
        # ressemble a une panne serveur alors que c'est la carte qui manque
        # de memoire.
        gc.collect()
        r = None
        try:
            r = urequests.get(self._url("/api/esp32/summary"),
                              timeout=NET_TIMEOUT)
            if r.status_code != 200:
                raise OSError(r.status_code)
            data = r.json()
        except Exception as e:
            # L'adresse de la carte accompagne l'erreur autant que la
            # memoire libre. Les deux pannes se ressemblent depuis le code
            # mais rien ne les rapproche : ECONNABORTED veut dire que la pile
            # reseau manquait de place, EHOSTUNREACH que la carte et le
            # serveur ne sont pas sur le meme reseau. Sans l'adresse, on
            # cherche une fuite memoire alors que la carte est sur le wifi
            # invite.
            print("fetch:", e, "| ip:", self.state.get("ip", "?"),
                  "| memoire libre:", gc.mem_free())
            self.state["online"] = False
            self.dirty = True
            self.t_poll = time.ticks_add(time.ticks_ms(),
                                         RETRY_MS - self._poll_interval())
            return False
        finally:
            if r is not None:
                r.close()

        data["online"] = True
        data["blink"] = self.state.get("blink", True)
        data["ip"] = self.state.get("ip", "")

        # Spotify met une seconde ou deux à refléter un changement de volume.
        # Sans ce garde-fou, un rafraîchissement qui tombe pendant qu'on
        # tourne ramènerait la jauge à l'ancienne valeur, et la molette
        # semblerait lutter contre l'écran.
        if time.ticks_diff(self._vol_hold, time.ticks_ms()) > 0:
            sp = data.get("spotify")
            if isinstance(sp, dict):
                sp["volume"] = self._vol_local

        self.state = data
        self._pos_at = time.ticks_ms()
        self.dirty = True
        gc.collect()
        return True

    def play_position(self):
        """La position de lecture, avancée localement depuis le dernier relevé.

        Interroger Spotify plus souvent pour voir un compteur bouger serait
        absurde : quand une piste joue, sa position avance d'une seconde par
        seconde et le firmware sait l'heure qu'il est. On extrapole donc, et
        le compteur devient fluide sans un seul appel supplémentaire.

        Le résultat est borné par la durée : sur une piste qui se termine, la
        dérive afficherait sinon un temps supérieur au morceau avant que le
        relevé suivant ne remette les pendules à l'heure.
        """
        sp = self.state.get("spotify") or {}
        pos = sp.get("position_s", 0)
        if not sp.get("playing"):
            return pos
        elapsed = time.ticks_diff(time.ticks_ms(), self._pos_at) // 1000
        dur = sp.get("duration_s", 0)
        pos += max(0, elapsed)
        return min(pos, dur) if dur else pos

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
        """Écrit la pochette sur la flash, seulement quand elle a changé.

        Le serveur la renvoie déjà en RGB565 inversé : l'ESP32 n'a aucun
        décodage à faire. Mais 160x160 pèse 51 Ko, bien au-delà de ce qu'on
        peut allouer d'un bloc en MicroPython — on écrit donc la réponse au
        fil de l'eau dans un fichier, que le pilote enverra ensuite à l'écran
        par tranches. La RAM n'en voit jamais plus d'un kilo-octet.

        Le fichier est réécrit à chaque changement de piste. La flash tient
        cent mille cycles d'effacement : quelques écritures par heure ne
        l'entament pas.
        """
        if tag == self._cover_tag:
            return
        self._cover_tag = tag
        self.cover = None
        if not tag:
            self.dirty = True
            return

        total = self.COVER * self.COVER * 2
        gc.collect()
        r = None
        got = 0
        try:
            r = urequests.get(self._url("/api/esp32/cover"),
                              timeout=NET_TIMEOUT)
            if r.status_code != 200:
                raise OSError(r.status_code)
            with open(COVER_FILE, "wb") as f:
                while got < total:
                    chunk = r.raw.read(min(1024, total - got))
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    # Sans ça, les vingt-cinq tampons d'un kilo s'accumulent
                    # et la pile réseau se retrouve sans mémoire au pire
                    # moment : au milieu de son propre téléchargement.
                    if got % 8192 == 0:
                        gc.collect()
        except Exception as e:
            print("cover:", e)
            self._cover_tag = None      # on retentera au prochain passage
            return
        finally:
            if r is not None:
                r.close()
            gc.collect()

        # Une image tronquée afficherait une bande de bruit sous la pochette :
        # mieux vaut ne rien montrer et réessayer.
        if got == total:
            self.cover = COVER_FILE
        else:
            print("cover: {} octets sur {}".format(got, total))
            self._cover_tag = None
        self.dirty = True

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

    def go(self, step):
        self.index = (self.index + step) % len(self.screens)
        self.g.sweep(SWEEP_MS)       # au lieu d'un flash noir
        self.dirty = True

    def handle(self, ev):
        if self.in_boot:
            return

        kind, arg = ev

        if kind == TURN:
            self.current().on_turn(arg, self)
            return

        if self.current().on_input(ev, self):
            return                   # l'écran a absorbé l'événement

        if kind == BTN_B and arg == LONG:
            self.index = 0           # retour à l'accueil
            self.g.sweep(SWEEP_MS)
            self.dirty = True
        elif kind == BTN_A and arg in (SHORT, REPEAT):
            self.go(-1)
        elif kind == BTN_C and arg in (SHORT, REPEAT):
            self.go(1)

    def _update_led(self):
        """La LED prend la couleur de l'ecran, et clignote s'il y a alerte.

        Une couleur fixe dit ou l'on est ; le clignotement dit qu'il y a
        quelque chose a regarder. Melanger les deux — une couleur d'alerte
        qui remplacerait celle de l'ecran — ferait perdre le reperage au
        moment ou il sert le plus.
        """
        color = theme.SCREEN_RGB[self.index % len(theme.SCREEN_RGB)]
        alert = (self.state.get("coach", {}).get("level") == "alert"
                 or not self.state.get("online", True))
        if alert and not self.state.get("blink", True):
            # On respire entre pleine intensite et moitie, jamais jusqu'a
            # l'extinction. Une LED qui s'eteint fait perdre la couleur de
            # l'ecran une demi-seconde sur deux, et le clignotement franc
            # accroche l'oeil bien plus qu'il ne le devrait pour un voyant
            # pose sur un bureau. Un battement doux se remarque sans
            # s'imposer, et la couleur reste lisible en permanence.
            color = tuple(c // 2 for c in color)
        self.led.show(color)

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

        print("memoire libre au demarrage :", gc.mem_free())

        while True:
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

        # Le capteur se lit toutes les dix secondes, pas a chaque image : sa
        # lecture bloque une vingtaine de millisecondes.
        if self.sensor.poll(now):
            self.dirty = True

        self._update_led()
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
