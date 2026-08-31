"""Trois boutons et un potentiomètre, ramenés à une file d'événements.

Le reste du firmware ne voit jamais un GPIO : il appelle poll() et reçoit des
événements déjà interprétés. Toute la logique d'anti-rebond et de filtrage
reste ici, ce qui rend les écrans testables sans matériel.

CÂBLAGE — boutons entre le GPIO et la masse, sans résistance externe : le
tirage interne est activé, un bouton relâché lit donc 1 et enfoncé 0.

    A (gauche)  GPIO 26     precedent            \
    B (select)  GPIO 27     valider / appui long  > repris de buttons.py
    C (droite)  GPIO 14     suivant              /
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
# L'encodeur émet le même marqueur : ce qui compte pour les écrans est la
# valeur, pas la nature du composant qui l'a produite.
TURN = POT

DEBOUNCE_MS = 25               # sous 25 ms, c'est du rebond mécanique
LONG_MS = 600                  # au-delà, l'intention est claire
REPEAT_AFTER_MS = 450          # maintien : on commence à répéter
REPEAT_EVERY_MS = 110          # puis à cette cadence

# Décodeur quadrature pour l'encodeur optionnel. L'index est
# (état précédent << 2) | état courant, la valeur le déplacement. Les
# transitions impossibles valent 0, ce qui absorbe les rebonds au lieu de
# compter des crans fantômes.
_QUAD = (0, -1, 1, 0,
         1, 0, 0, -1,
         -1, 0, 0, 1,
         0, 1, -1, 0)


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

    L'ÉCHELLE SE CALIBRE TOUTE SEULE

    Une borne écrite en dur ne peut pas savoir jusqu'où TON potard va. Le
    convertisseur de l'ESP32 est non linéaire près de 0 V et sature avant
    3,3 V, à une valeur qui dépend de la puce, de l'alimentation et des
    tolérances de la piste résistive. Fixer le maximum à 4000 alors que le
    tien plafonne à 3600, c'est un potard qui ne monte jamais au-delà de
    90 % — sans que rien ne l'indique.

    On mémorise donc les extrêmes réellement vus et on tend l'échelle
    dessus. Le premier balayage complet suffit à calibrer ; avant ça, une
    plage par défaut évite les valeurs absurdes.

    Les 2 % de chaque bout sont collés à 0 et 100. Sans cette marge, la
    dernière fraction de course serait injoignable dès que le bruit dépasse
    d'un point ce qui a été observé.
    """

    RAW_MIN, RAW_MAX = 120, 4000   # plage supposée tant que rien n'est vu
    ALPHA_NUM, ALPHA_DEN = 1, 4    # lissage : 1/4 de la nouvelle mesure
    DEADBAND = 1                   # en pourcents
    EDGE = 2                       # % collés aux extrêmes
    MIN_SPAN = 300                 # en deçà, on n'a pas vu assez de course

    def __init__(self, pin_no):
        self.adc = ADC(Pin(pin_no))
        self.adc.atten(ADC.ATTN_11DB)   # pleine échelle 0-3,3 V
        self.ema = self.adc.read()
        # Bornes impossibles : la première mesure les remplace toutes deux.
        self.lo, self.hi = 4095, 0
        self.last = self._pct()

    def _pct(self):
        raw = self.ema
        if raw < self.lo:
            self.lo = raw
        if raw > self.hi:
            self.hi = raw

        lo, hi = self.lo, self.hi
        if hi - lo < self.MIN_SPAN:
            # Pas encore assez de course observée : on s'en remet à la plage
            # supposée plutôt que d'amplifier le bruit sur trois points.
            lo, hi = self.RAW_MIN, self.RAW_MAX

        if raw <= lo:
            return 0
        if raw >= hi:
            return 100
        pct = ((raw - lo) * 100) // (hi - lo)
        if pct <= self.EDGE:
            return 0
        if pct >= 100 - self.EDGE:
            return 100
        return pct

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


class Encoder:
    """Encodeur rotatif en quadrature, lu par interruption.

    On compte les quarts de cran dans l'interruption — qui doit rester
    minuscule — et on convertit en crans dans poll(). La plupart des encodeurs
    mécaniques font quatre transitions par cran ; ajuste STEPS_PER_DETENT si
    le tien réagit deux fois trop ou deux fois trop peu.
    """

    STEPS_PER_DETENT = 4

    def __init__(self, clk_no, dt_no):
        self.clk = Pin(clk_no, Pin.IN, Pin.PULL_UP)
        self.dt = Pin(dt_no, Pin.IN, Pin.PULL_UP)
        self._state = (self.clk.value() << 1) | self.dt.value()
        self._acc = 0
        trig = Pin.IRQ_RISING | Pin.IRQ_FALLING
        self.clk.irq(trigger=trig, handler=self._irq)
        self.dt.irq(trigger=trig, handler=self._irq)

    def _irq(self, _pin):
        cur = (self.clk.value() << 1) | self.dt.value()
        self._acc += _QUAD[(self._state << 2) | cur]
        self._state = cur

    def poll(self, out):
        acc = self._acc
        step = self.STEPS_PER_DETENT
        while acc >= step:
            acc -= step
            out.append((TURN, 1))
        while acc <= -step:
            acc += step
            out.append((TURN, -1))
        self._acc = acc


class _EncoderAsPot:
    """Fait passer un encodeur pour un potard, vu des écrans.

    L'encodeur est relatif ; le reste du firmware raisonne en position de 0
    à 100. On accumule donc les crans dans un compteur borné. C'est le seul
    endroit qui connaît la différence — et comme un encodeur n'a aucune
    position physique à trahir, il n'a jamais besoin de rattrapage.
    """

    STEP = 4                        # % gagnés par cran

    def __init__(self, clk, dt):
        self.enc = Encoder(clk, dt)
        self.last = 50              # on démarre au milieu, faute de mieux

    def value(self):
        return self.last

    def poll(self, out):
        moves = []
        self.enc.poll(moves)
        if not moves:
            return
        for _kind, delta in moves:
            self.last = max(0, min(100, self.last + delta * self.STEP))
        out.append((POT, self.last))


class Input:
    """Toutes les entrées derrière un seul poll()."""

    def __init__(self, pin_a=26, pin_b=27, pin_c=14, pot=34,
                 clk=None, dt=None):
        """Potard OU encodeur, jamais les deux.

        Renseigner clk et dt bascule sur l'encodeur et ignore le potard. Les
        deux produisent le même événement POT avec une valeur de 0 à 100 :
        les écrans ne savent pas lequel est branché, et n'ont pas à le
        savoir.
        """
        # A et C se répètent quand on les maintient : c'est ce qui permet de
        # faire défiler sans toucher au potard. B ne se répète pas — son
        # appui long a un sens à lui.
        self.buttons = (
            Button(pin_a, BTN_A, repeats=True),
            Button(pin_b, BTN_B),
            Button(pin_c, BTN_C, repeats=True),
        )
        if clk is not None and dt is not None:
            self.pot = _EncoderAsPot(clk, dt)
            # Un encodeur n'a pas de position physique : rien ne peut être
            # écrasé par accident, donc aucun rattrapage n'a de sens.
            self.absolute = False
        elif pot is not None:
            self.pot = Pot(pot)
            self.absolute = True
        else:
            self.pot = None
            self.absolute = False

    def poll(self):
        """Renvoie la liste des événements survenus depuis le dernier appel."""
        out = []
        now = time.ticks_ms()
        for b in self.buttons:
            b.poll(now, out)
        if self.pot is not None:
            self.pot.poll(out)
        return out
