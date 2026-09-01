"""Le DHT11 : température et humidité de la pièce.

Il sert à comparer la pièce et le dehors. La météo de l'API dit ce qu'il
fait dans la ville ; ce capteur dit ce qu'il fait à un mètre de toi, et les
deux se contredisent souvent — c'est justement l'intérêt.

CE QU'UN DHT11 IMPOSE

  - Une lecture prend une vingtaine de millisecondes pendant lesquelles le
    processeur ne fait rien d'autre : le protocole se décode au chronomètre.
    On ne le lit donc pas à chaque image.
  - Il refuse d'être interrogé plus d'une fois toutes les deux secondes. En
    dessous, il renvoie l'ancienne mesure ou une erreur de checksum.
  - Sa précision est modeste : ±2 °C et ±5 % d'humidité, en pas de 1. On
    n'affiche donc pas de décimale, elle serait inventée.

Une lecture ratée est normale et fréquente : le décodage est sensible aux
interruptions, dont le wifi est friand. On garde la dernière valeur valide
plutôt que de faire clignoter un tiret à chaque raté.
"""
import time

READ_EVERY_MS = 10000     # bien au-delà des 2 s minimales du composant
STALE_MS = 120000         # au-delà, la mesure ne vaut plus rien


class Dht:
    def __init__(self, pin_no, kind="dht11", pullup=True):
        from machine import Pin
        import dht
        cls = dht.DHT22 if kind == "dht22" else dht.DHT11
        # Le tirage interne de l'ESP32 (~45 kOhm) est bien plus faible que
        # les 10 kOhm que reclame un DHT nu, mais sur vingt centimetres de
        # fil il suffit souvent. On l'active donc : ca ne coute rien et ca
        # peut eviter d'attendre une resistance.
        #
        # Ce n'est PAS un remplacement. Si les lectures echouent une fois
        # sur trois ou tombent en checksum, c'est ce tirage trop faible qui
        # est en cause, et il faut la vraie resistance de 10 kOhm entre DATA
        # et VCC.
        pin = Pin(pin_no, Pin.IN, Pin.PULL_UP) if pullup else Pin(pin_no)
        self.d = cls(pin)
        self.t = None
        self.h = None
        self.at = 0
        self.next = 0
        self.fails = 0

    def poll(self, now):
        """Lit le capteur si le moment est venu. Renvoie True si ça a bougé."""
        if time.ticks_diff(now, self.next) < 0:
            return False
        self.next = time.ticks_add(now, READ_EVERY_MS)
        try:
            self.d.measure()
            t, h = self.d.temperature(), self.d.humidity()
        except Exception as e:
            # Un raté isolé n'est pas une panne : le protocole se décode au
            # chronomètre et la moindre interruption le perturbe. On ne le
            # signale qu'après plusieurs échecs de suite.
            self.fails += 1
            if self.fails in (5, 50):
                print("dht:", e)
            return False
        self.fails = 0
        changed = (t != self.t or h != self.h)
        self.t, self.h, self.at = t, h, now
        return changed

    def reading(self, now):
        """(temperature, humidite) ou (None, None) si rien de fiable."""
        if self.t is None or time.ticks_diff(now, self.at) > STALE_MS:
            return None, None
        return self.t, self.h


    def state(self):
        """« ok », « muet » ou « absent » — pour que l'écran le dise.

        « Pas de capteur » quand il est en fait câblé mais silencieux envoie
        chercher au mauvais endroit. Les deux cas méritent deux mots
        différents.
        """
        if self.t is not None:
            return "ok"
        return "muet"


class NoSensor:
    """Aucun capteur câblé. Le reste du firmware n'a pas à le savoir."""

    def poll(self, now):
        return False

    def reading(self, now):
        return None, None

    def state(self):
        return "absent"


def make(pin=None, kind="dht11", pullup=True):
    """Fabrique le capteur, ou un objet inerte s'il manque ou refuse.

    Un capteur absent ou mal câblé ne doit pas empêcher l'afficheur de
    démarrer : c'est un complément, pas une dépendance.
    """
    if pin is None:
        return NoSensor()
    try:
        return Dht(pin, kind, pullup)
    except Exception as e:
        print("dht:", e)
        return NoSensor()
