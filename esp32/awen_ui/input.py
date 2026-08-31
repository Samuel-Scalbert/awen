"""Trois boutons et un potentiomètre, ramenés à une file d'événements.

Le reste du firmware ne voit jamais un GPIO : il appelle poll() et reçoit des
événements déjà interprétés. Toute la logique d'anti-rebond et de filtrage
reste ici, ce qui rend les écrans testables sans matériel.

CÂBLAGE — boutons entre le GPIO et la masse, sans résistance externe : le
tirage interne est activé, un bouton relâché lit donc 1 et enfoncé 0.

    A (gauche)  GPIO 32     precedent
    B (milieu)  GPIO 33     valider  /  appui long = accueil
    C (droite)  GPIO 25     suivant
    potard      GPIO 34     valeurs  (extremes sur 3V3 et GND, curseur ici)

GPIO 34 n'est pas un choix esthétique. L'ESP32 a deux convertisseurs
analogiques et **ADC2 cesse de fonctionner dès que le wifi est actif** : un
potentiomètre câblé sur GPIO 25 ou 26 lirait n'importe quoi une fois connecté.
Les broches 32 à 39 sont sur ADC1 ; 34 à 39 sont en entrée seule, donc sans
tirage interne parasite. C'est exactement ce qu'on veut pour un potard.
"""
from machine import ADC, Pin
import time

# Événements. Des entiers plutôt que des chaînes : comparaison plus rapide,
# et aucune allocation dans la boucle principale.
BTN_A, BTN_B, BTN_C = 0, 1, 2
SHORT, LONG, REPEAT = 0, 1, 2
POT = 9                        # (POT, valeur) où valeur va de 0 à 100

DEBOUNCE_MS = 25               # sous 25 ms, c'est du rebond mécanique
LONG_MS = 600                  # au-delà, l'intention est claire
REPEAT_AFTER_MS = 450          # maintien : on commence à répéter
REPEAT_EVERY_MS = 110          # puis à cette cadence


class Button:
    """Un bouton anti-rebondi, capable de distinguer court, long et maintien."""

    def __init__(self, pin_no, ident, repeats=False):
        self.pin = Pin(pin_no, Pin.IN, Pin.PULL_UP)
        self.id = ident
        self.repeats = repeats
        self.down = False
        self.t_change = 0
        self.t_repeat = 0
        # Vrai dès qu'un appui long ou une répétition a été signalé : le
        # relâchement ne doit alors plus produire d'appui court par-dessus.
        self.consumed = False

    def poll(self, now, out):
        pressed = not self.pin.value()          # actif à l'état bas

        if pressed != self.down:
            if time.ticks_diff(now, self.t_change) < DEBOUNCE_MS:
                return
            self.t_change = now
            self.down = pressed
            if pressed:
                self.consumed = False
                self.t_repeat = now
            elif not self.consumed:
                out.append((self.id, SHORT))
            return

        if not pressed:
            return

        held = time.ticks_diff(now, self.t_change)

        if self.repeats:
            if held >= REPEAT_AFTER_MS and \
                    time.ticks_diff(now, self.t_repeat) >= REPEAT_EVERY_MS:
                self.t_repeat = now
                self.consumed = True
                out.append((self.id, REPEAT))
        elif not self.consumed and held >= LONG_MS:
            self.consumed = True
            out.append((self.id, LONG))


class Pot:
    """Potentiomètre lu sur ADC1, filtré et débruité.

    Un convertisseur d'ESP32 est bruyant : à curseur immobile, les lectures
    brutes sautent d'une trentaine de points sur 4095. Sans filtrage, une
    valeur à l'écran tremblerait en permanence et chaque tremblement
    déclencherait un redessin.

    Deux protections, dans cet ordre :

      1. une moyenne glissante exponentielle, qui lisse le bruit sans garder
         d'historique en mémoire ;
      2. une zone morte : on ne signale un changement qu'au-delà d'un point
         de pourcentage, sinon le lissage tremblerait plus lentement, mais
         il tremblerait quand même.

    Les extrémités de l'échelle sont volontairement rognées. Le convertisseur
    de l'ESP32 est non linéaire près de 0 V et sature avant 3,3 V : sans ça,
    tu ne pourrais jamais atteindre ni 0 % ni 100 %.
    """

    RAW_MIN, RAW_MAX = 120, 4000   # plage réellement exploitable
    ALPHA_NUM, ALPHA_DEN = 1, 4    # lissage : 1/4 de la nouvelle mesure
    DEADBAND = 1                   # en pourcents

    def __init__(self, pin_no):
        self.adc = ADC(Pin(pin_no))
        self.adc.atten(ADC.ATTN_11DB)   # pleine échelle 0-3,3 V
        self.ema = self.adc.read()
        self.last = self._pct()

    def _pct(self):
        raw = self.ema
        if raw <= self.RAW_MIN:
            return 0
        if raw >= self.RAW_MAX:
            return 100
        return ((raw - self.RAW_MIN) * 100) // (self.RAW_MAX - self.RAW_MIN)

    def value(self):
        """Position courante en pourcents, sans passer par la file."""
        return self.last

    def poll(self, out):
        self.ema += (self.adc.read() - self.ema) * self.ALPHA_NUM \
            // self.ALPHA_DEN
        pct = self._pct()
        if abs(pct - self.last) >= self.DEADBAND:
            self.last = pct
            out.append((POT, pct))


class Input:
    """Toutes les entrées derrière un seul poll()."""

    def __init__(self, pin_a=32, pin_b=33, pin_c=25, pot=34):
        # A et C se répètent quand on les maintient : c'est ce qui permet de
        # faire défiler sans toucher au potard. B ne se répète pas — son
        # appui long a un sens à lui.
        self.buttons = (
            Button(pin_a, BTN_A, repeats=True),
            Button(pin_b, BTN_B),
            Button(pin_c, BTN_C, repeats=True),
        )
        self.pot = Pot(pot) if pot is not None else None

    def poll(self):
        """Renvoie la liste des événements survenus depuis le dernier appel."""
        out = []
        now = time.ticks_ms()
        for b in self.buttons:
            b.poll(now, out)
        if self.pot is not None:
            self.pot.poll(out)
        return out
