"""Navigation, réseau et boucle principale de l'afficheur Awen.

TROIS HORLOGES INDÉPENDANTES, ET C'EST VOLONTAIRE

  - les entrées sont lues à ~60 Hz, sinon un appui semble mou ;
  - l'écran n'est redessiné que si quelque chose a changé (`dirty`), et le
    canevas ne repeint que les éléments différents : une horloge qui avance
    d'une minute ne coûte que les segments qui changent ;
  - le serveur n'est interrogé que toutes les 30 secondes — sauf sur Spotify,
    où une piste change trop souvent pour attendre autant.

Les mélanger dans une seule cadence est le moyen le plus sûr d'obtenir une
interface qui rame : on redessinerait tout à chaque image, ou on lirait les
boutons une fois par seconde.

LA VEILLE N'ÉTEINT QUE CE QUI ÉCLAIRE

Personne devant le bureau pendant dix minutes : le rétroéclairage et la LED
s'éteignent. Le reste continue — le wifi, les relevés serveur, l'horloge.
C'est délibéré : au réveil l'écran doit être JUSTE, pas rafraîchi sous les
yeux. Un afficheur qui montre l'heure d'il y a dix minutes le temps de se
recharger serait pire que celui qui n'aurait jamais dormi.

Ce qu'on cesse de faire, c'est de DESSINER. Pousser des pixels sur un
panneau noir ne sert personne, et le panneau garde son image : au réveil, le
canevas n'envoie que ce qui a réellement changé.

L'HEURE AVANCE TOUTE SEULE ENTRE DEUX RELEVÉS

La carte n'a pas d'horloge sauvegardée, mais elle sait compter. Le serveur
donne l'heure à la seconde près ; entre deux relevés, on ajoute le temps
écoulé. La minute change donc à l'heure, et non jusqu'à trente secondes
plus tard : sur une horloge qui occupe un quart de l'écran, cela se voit.

LA MOLETTE ENVOIE UN DÉPLACEMENT

Un TURN vaut ±1 cran, jamais une valeur absolue : l'écran courant l'ajoute
à ce qu'il affiche. Rien ne saute en changeant d'écran, et il n'y a donc
aucun mécanisme de rattrapage ici. Le pourquoi est dans input.py.
"""
import gc
import time

import machine
import network
import urequests

try:
    import esp32            # le tas de l'ESP-IDF, celui du wifi
except ImportError:
    esp32 = None            # le simulateur

import backlight as backlight_mod
from canvas import Canvas
from input import BTN_A, BTN_B, BTN_C, Input, LONG, REPEAT, SHORT, TURN
import led as led_mod
import presence as presence_mod
import screens
import sensor as sensor_mod
import theme

POLL_MS = 30000          # rafraîchissement des données serveur
POLL_SPOTIFY_MS = 5000   # une piste change trop souvent pour attendre 30 s
# Apres un echec, on retente vite : attendre le cycle complet laisserait
# l'ecran affirmer « HORS LIGNE » une demi-minute pour une socket avortee.
RETRY_MS = 4000
FRAME_MS = 16            # lecture des entrées
BLINK_MS = 530           # battement de la LED en cas d'alerte
# Huit positions a 150 ms : un tour de logo en 1,2 seconde. Plus vite,
# il se lirait comme un sablier — donc comme une attente. Plus lent, on
# ne verrait plus qu'il tourne.
SPIN_MS = 150
NET_TIMEOUT = 6          # secondes ; au-delà, on garde l'écran précédent
COVER = 144              # côté de la pochette, demandé au serveur (?size=)
COVER_FILE = "/cover.bin"   # 41 Ko : sur la flash, jamais en RAM

# Toutes les dix minutes, la page est repeinte en place. Voir _tick().
REPAINT_MS = 600000

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

# LA CARTE DIT AU SERVEUR POURQUOI ELLE A REDÉMARRÉ
#
# Un redémarrage efface la console série, et personne n'y est branché quand
# il arrive. La puce, elle, garde la cause : on l'envoie au premier relevé
# réussi, et le serveur la range à côté du dernier état que la carte lui
# avait annoncé (voir /api/esp32/journal). Les trois pannes ne se cherchent
# pas au même endroit :
#
#   ALIM     coupure ou chute de tension (câble, port USB, pic du wifi),
#            mais aussi la broche EN : le bouton, ou un PC qui ouvre le port
#            série. MicroPython range tout cela sous la même cause.
#   PLANTAGE erreur dans le C de MicroPython ou de l'ESP-IDF
#   GARDE    un chien de garde de l'ESP-IDF : quelque chose a bloqué
#
# Une erreur de la boucle part aussi, au plus une par minute : une panne qui
# se répète à chaque image ne doit ni inonder le serveur ni ralentir l'écran.
CAUSES = {
    getattr(machine, "PWRON_RESET", -1): "ALIM",
    getattr(machine, "HARD_RESET", -2): "EN",
    getattr(machine, "WDT_RESET", -3): "GARDE",
    getattr(machine, "DEEPSLEEP_RESET", -4): "VEILLE",
    getattr(machine, "SOFT_RESET", -5): "PLANTAGE",
}
JOURNAL_MS = 60000

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
        self.g = Canvas(display, theme.load())
        self.io = Input(**config.get("pins", {}))
        self.led = led_mod.make(**config.get("led", {}))
        self.sensor = sensor_mod.make(**config.get("sensor", {}))
        self.backlight = backlight_mod.make(config.get("backlight"))
        self.sonar = presence_mod.make(**config.get("presence", {}))
        self.awake = True
        self.cfg = config

        self.screens = [cls() for cls in screens.CAROUSEL]
        self.index = 0
        self.boot = screens.Boot()
        self.in_boot = True

        # `online` distingue « pas encore de données » de « serveur injoignable ».
        self.state = {"online": False, "ip": "", "spin": 0}
        self.dirty = True
        self.t_poll = 0
        self.t_spin = 0
        self.t_repaint = 0
        self._hm = None             # minutes depuis minuit, au dernier relevé
        self._sec = 0
        self._hm_at = 0
        self._min_vue = None        # la minute actuellement à l'écran
        self._sonar_vu = None       # ce que l'écran montre du sonar

        self.wlan = None
        self._vol_pending = None
        self._vol_at = 0
        self._vol_local = 0
        self._vol_hold = 0          # jusqu'à quand la valeur locale prime
        self.cover = None           # pochette en RGB565 brut
        self._cover_tag = None
        self._pos_at = 0            # quand la position de lecture a été lue
        # Debit du dernier transfert, en kilo-octets par seconde. Voir
        # _mesure_debit().
        self.net_kbs = None
        self.net_octets = 0

        # Le journal : ce qui reste à dire au serveur, et de quoi décrire
        # l'état de la carte à chaque relevé. Voir CAUSES.
        try:
            cause = CAUSES.get(machine.reset_cause(), "?")
        except Exception:
            cause = "?"
        self._a_dire = [{"evt": "demarrage", "cause": cause}]
        self._dit_at = None
        self.erreurs = 0            # exceptions rattrapées par la boucle
        self.echecs = 0             # relevés qui n'ont pas abouti
        self._up_ms = 0
        self._up_at = time.ticks_ms()
        # Le tampon de la pochette, alloué une fois pour toutes. Voir
        # fetch_cover().
        self._tampon = bytearray(1024)

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

    def _mesure_debit(self, octets, depuis):
        """Enregistre le debit du transfert qui vient de finir.

        CE N'EST PAS LA VITESSE DU WIFI, ET IL NE FAUT PAS LE PRETENDRE.

        C'est le debit utile de bout en bout : la carte, l'air, le serveur et
        le temps qu'il met a repondre, tout compris. Sur un petit transfert
        la latence domine et le chiffre parait bas alors que la liaison va
        tres bien — d'ou l'affichage de la taille a cote, sans laquelle le
        nombre ne veut rien dire.

        C'est justement ce qu'on veut surveiller : le RSSI dit si le signal
        arrive, celui-ci dit si les donnees arrivent. Les deux se degradent
        rarement en meme temps, et c'est le second qui gene vraiment.

        UNE SEULE SOURCE : LE RESUME.

        La pochette Spotify ferait un bien meilleur echantillon — 25 Ko
        contre deux — mais elle ne se telecharge que sur un ecran, et
        melanger les deux ferait sauter le chiffre d'un facteur dix pour une
        raison etrangere au reseau. Un echantillon toujours identique, toutes
        les trente secondes, se compare a lui-meme : c'est ce qu'on lit sur
        cette ligne, une tendance, pas un test de debit.
        """
        ms = time.ticks_diff(time.ticks_ms(), depuis)
        if octets <= 0 or ms <= 0:
            return
        self.net_octets = octets
        self.net_kbs = (octets * 1000) // (ms * 1024)

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
        debut = time.ticks_ms()
        try:
            r = urequests.get(self._url("/api/esp32/pages") + self._etat(),
                              timeout=NET_TIMEOUT)
            if r.status_code != 200:
                raise OSError(r.status_code)
            # .content avant .json() : urequests garde le corps en cache,
            # la lecture n'a donc pas lieu deux fois.
            octets = len(r.content)
            data = r.json()
            self._mesure_debit(octets, debut)
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
            self.echecs += 1
            self.state["online"] = False
            self.dirty = True
            self.t_poll = time.ticks_add(time.ticks_ms(),
                                         RETRY_MS - self._poll_interval())
            return False
        finally:
            if r is not None:
                r.close()

        data["online"] = True
        data["spin"] = self.state.get("spin", 0)
        data["ip"] = self.state.get("ip", "")
        if data.get("min") is not None:
            self._hm = data["min"]
            self._sec = data.get("sec", 0)
            self._hm_at = time.ticks_ms()

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
        self._raconte()
        return True

    # ------------------------------------------------------------ journal

    def _uptime(self):
        """Secondes depuis le démarrage.

        Cumulées relevé après relevé : ticks_ms() reboucle au bout de
        douze jours, et un ticks_diff() depuis le démarrage deviendrait faux
        au-delà de six. Entre deux relevés, il ne passe jamais plus de
        trente secondes.
        """
        now = time.ticks_ms()
        self._up_ms += time.ticks_diff(now, self._up_at)
        self._up_at = now
        return self._up_ms // 1000

    def _idf(self):
        """Le tas de l'ESP-IDF, où vivent le wifi et lwip : (libre, le plus
        bas atteint). Celui de MicroPython peut aller bien pendant que
        celui-ci s'épuise, et c'est alors la pile réseau qui fait tomber la
        carte, sans aucune exception Python."""
        if esp32 is None:
            return 0, 0
        try:
            h = esp32.idf_heap_info(esp32.HEAP_DATA)
            return sum(x[1] for x in h), sum(x[3] for x in h)
        except Exception:
            return 0, 0

    def _etat(self):
        """L'état de la carte, joint à chaque relevé.

        Quelques octets de plus dans l'adresse, et le serveur sait toujours
        comment allait la carte juste avant qu'elle ne redémarre : depuis
        combien de temps elle tournait, sur quelle page, avec quelle mémoire.
        Une fuite se lit dans la pente de `mem`, une alimentation faible
        dans un redémarrage sans aucun signe avant-coureur.
        """
        libre, bas = self._idf()
        return "&up={}&mem={}&idf={}&bas={}&p={}&e={}&n={}".format(
            self._uptime(), gc.mem_free(), libre, bas, self.current().NAME,
            self.erreurs, self.echecs)

    def note(self, evt, msg):
        """Garde une ligne pour le serveur, au plus une par minute."""
        now = time.ticks_ms()
        if self._dit_at is not None and \
                time.ticks_diff(now, self._dit_at) < JOURNAL_MS:
            return
        if len(self._a_dire) >= 4:
            return
        self._dit_at = now
        self._a_dire.append({"evt": evt, "msg": msg[:120]})

    def _raconte(self):
        """Envoie ce qui attend. Appelé juste après un relevé réussi : le
        serveur répond, ce n'est pas le moment de bloquer sur un délai."""
        while self._a_dire:
            ligne = self._a_dire[0]
            ligne["up"] = self._up_ms // 1000
            ligne["mem"] = gc.mem_free()
            if not self._post("/api/esp32/journal", ligne):
                return
            self._a_dire.pop(0)

    def minutes(self):
        """L'heure qu'il est, en minutes depuis minuit. None avant le
        premier relevé : sans réseau, la carte ne sait pas l'heure."""
        if self._hm is None:
            return None
        s = (self._hm * 60 + self._sec
             + time.ticks_diff(time.ticks_ms(), self._hm_at) // 1000)
        return (s // 60) % 1440

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

    def fetch_cover(self, tag):
        """Écrit la pochette sur la flash, seulement quand elle a changé.

        Le serveur la renvoie déjà en RGB565 inversé : l'ESP32 n'a aucun
        décodage à faire. Mais 144x144 pèse 41 Ko, bien au-delà de ce qu'on
        peut allouer d'un bloc en MicroPython — on écrit donc la réponse au
        fil de l'eau dans un fichier, que le canevas enverra ensuite à l'écran
        par tranches. La RAM n'en voit jamais plus d'un kilo-octet.

        Et ce kilo-octet est toujours le même : readinto() remplit un tampon
        alloué au démarrage. Avec read(1024), chaque tranche était un objet
        neuf, quarante et un par pochette, à chaque piste : de quoi morceler
        le tas au moment précis où la pile réseau a besoin de place.

        L'empreinte part avec la demande : le serveur sert la pochette qu'il
        a annoncée, pas celle d'une piste qui aurait changé entre-temps, et
        n'a pas à redemander à Spotify ce qu'il sait déjà.

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
            # La taille voyage avec la demande : c'est la carte qui sait
            # quelle place la page lui réserve, le serveur s'y plie.
            r = urequests.get(self._url("/api/esp32/cover")
                              + "&size={}&tag={}".format(self.COVER, tag),
                              timeout=NET_TIMEOUT)
            if r.status_code != 200:
                raise OSError(r.status_code)
            buf = self._tampon
            vue = memoryview(buf)
            with open(COVER_FILE, "wb") as f:
                while got < total:
                    reste = total - got
                    n = r.raw.readinto(buf if reste >= len(buf)
                                       else vue[:reste])
                    if not n:
                        break
                    f.write(buf if n == len(buf) else vue[:n])
                    got += n
        except Exception as e:
            print("cover:", e)
            self.echecs += 1
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
        # En arrivant sur Spotify on relève tout de suite : sans ça la page
        # montrerait la piste d'il y a trente secondes, et pas de pochette
        # avant le prochain passage.
        if self.current().NAME == "spotify":
            self.t_poll = 0

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
        # Une LED qui brille encore devant un ecran noir est la seule chose
        # qu'on verra dans la piece : elle s'eteint avec lui, sinon la veille
        # ne veille rien.
        if not self.awake:
            self.led.show((0, 0, 0))
            return

        color = theme.SCREEN_RGB[self.index % len(theme.SCREEN_RGB)]
        alert = not self.state.get("online", True)
        if alert and (time.ticks_ms() // BLINK_MS) & 1:
            # On respire entre pleine intensite et moitie, jamais jusqu'a
            # l'extinction. Une LED qui s'eteint fait perdre la couleur de
            # l'ecran une demi-seconde sur deux, et le clignotement franc
            # accroche l'oeil bien plus qu'il ne le devrait pour un voyant
            # pose sur un bureau. Un battement doux se remarque sans
            # s'imposer, et la couleur reste lisible en permanence.
            color = tuple(c // 2 for c in color)
        self.led.show(color)

    def _update_presence(self, now):
        """Endort et reveille l'afficheur selon ce que voit le sonar.

        Le reveil est immediat des qu'une presence est confirmee ; le
        sommeil attend le delai complet. L'asymetrie est voulue : se tromper
        en rallumant coute une lampe allumee pour rien, se tromper en
        eteignant coupe l'ecran sous le nez de quelqu'un.

        LE REVEIL SUIT L'ETAT, PAS LE FRONT.

        On se reveillait sur la TRANSITION absent->present renvoyee par
        poll(). Il suffisait qu'elle soit manquee une fois — et les echos
        perdus y suffisaient — pour que l'ecran reste noir indefiniment.
        Lire `present` ne peut pas rater d'evenement : au pire on regarde
        une demi-seconde trop tard. L'endormissement appelle forget() pour
        que cet etat reparte de zero, sinon l'ecran se rallumerait aussitot
        sur une presence que le delai vient de declarer perimee.
        """
        self.sonar.poll(now)

        if not self.awake:
            if self.sonar.present:
                self.awake = True
                self.backlight.wake()
                # L'ecran a garde son image, mais le contenu a vieilli : on
                # force un redessin, que le canevas reduira a ce qui a
                # reellement change.
                self.dirty = True
            return

        if self.sonar.expired(now):
            self.awake = False
            self.backlight.sleep()
            self.sonar.forget()

    def _wake_on_input(self, now):
        """Un appui rallume, meme sans passer devant le capteur.

        Le sonar peut rater quelqu'un d'immobile ou assis de biais. Sans
        cette porte de sortie, l'ecran resterait noir sous les doigts de son
        proprietaire — le genre de defaut qui fait debrancher l'objet.
        """
        if self.awake:
            return False
        self.awake = True
        self.backlight.wake()
        self.dirty = True
        # Sans ca, _update_presence rendormirait l'ecran a l'image suivante :
        # le chronometre du sonar aurait toujours dix minutes de retard.
        self.sonar.seen(now)
        return True

    # ------------------------------------------------------------ boucle

    def _boot_draw(self):
        self.state["spin"] = self.state.get("spin", 0) + 1
        self.boot.draw(self.g, self.state, self)

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
        # lui reste, sans figer l'ecran : le logo continue de tourner.
        while not self._wifi_ok():
            if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                return False
            self._boot_draw()
            time.sleep_ms(SPIN_MS)
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
                self.erreurs += 1
                try:
                    self.note("erreur", "{} {} ({})".format(
                        type(e).__name__, e, self.current().NAME))
                except Exception:
                    pass
                time.sleep_ms(500)

    def _tick(self):
        """Une image. Tout ce qui peut échouer est appelé depuis ici.

        Découpé de run() pour qu'une exception soit rattrapée sans tuer la
        boucle : la panne coûte une image, pas l'afficheur.
        """
        now = time.ticks_ms()

        events = self.io.poll()
        if events and self._wake_on_input(now):
            # Le geste qui reveille ne fait QUE reveiller. L'appliquer en
            # plus changerait d'ecran ou lancerait une piste au moment ou on
            # cherchait juste a voir l'heure.
            events = []
        for ev in events:
            self.handle(ev)

        # Le capteur se lit toutes les dix secondes, pas a chaque image : sa
        # lecture bloque une vingtaine de millisecondes.
        if self.sensor.poll(now):
            self.dirty = True

        self._update_presence(now)
        self._update_led()
        self._flush_volume(now)

        # LE LOGO TOURNE SANS REDESSINER LA PAGE.
        #
        # Il change sept fois par seconde : repasser par draw() pour si peu
        # ferait redire quatre-vingts elements au canevas a chaque tour. On
        # lui demande directement l'image suivante, un envoi de 16x16.
        #
        # Il ne tourne pas dans le noir : il n'a rien a dire a personne
        # quand le panneau est eteint.
        if self.awake and time.ticks_diff(now, self.t_spin) >= SPIN_MS:
            self.t_spin = now
            spin = self.state.get("spin", 0) + 1
            self.state["spin"] = spin
            if not self.dirty:
                self.g.logo(screens.LOGO_X, screens.LOGO_Y, spin,
                            theme.LOGO_RING)

        # La minute a tourne : c'est le seul evenement que rien d'autre ne
        # signale, puisque l'heure est comptee ici et non recue.
        m = self.minutes()
        if m != self._min_vue:
            self._min_vue = m
            self.dirty = True

        # Le sonar n'interesse que l'accueil, qui affiche ce qu'il voit :
        # la distance, et sa couleur selon qu'il y a quelqu'un. Les deux
        # comptent : la presence ne se confirme qu'a la deuxieme lecture,
        # donc une image APRES la distance qui l'a fait changer.
        vu = self.sonar.distance if self.sonar.present else -self.sonar.distance - 1
        if vu != self._sonar_vu:
            self._sonar_vu = vu
            if self.current().NAME == "home":
                self.dirty = True

        self.current().tick(now, self)

        # TOUTES LES DIX MINUTES, LA PAGE EST REPEINTE EN PLACE.
        #
        # Le canevas ne repeint que ce qui change : un pixel abime en route,
        # par un parasite sur le bus, resterait la jusqu'au prochain
        # changement de l'element, parfois des heures. On lui fait tout
        # oublier SANS effacer l'ecran : chaque element se repeint sur
        # lui-meme, il n'y a aucun eclair noir.
        if self.awake and time.ticks_diff(now, self.t_repaint) >= REPAINT_MS:
            self.t_repaint = now
            self.g.forget_all()
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

        if self.dirty and self.awake:
            self.dirty = False
            self.current().draw(self.g, self.state, self)

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
