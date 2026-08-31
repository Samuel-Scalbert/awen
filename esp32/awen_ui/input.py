"""Trois boutons et un encodeur rotatif, ramenés à une file d'événements.

Le reste du firmware ne voit jamais un GPIO : il appelle poll() et reçoit des
événements déjà interprétés (appui court, appui long, cran de molette). Ça
garde toute la logique d'anti-rebond ici, et rend les écrans testables sans
matériel.

Câblage attendu — boutons entre le GPIO et la masse, sans résistance externe :
on active le tirage interne, un bouton relâché lit donc 1 et un bouton
enfoncé lit 0.

    A (gauche)  GPIO 32        precedent / moins
    B (milieu)  GPIO 33        valider   / appui long = accueil
    C (droite)  GPIO 25        suivant   / plus
    encodeur    CLK 26, DT 27  valeurs continues
    (le clic de l'encodeur, si tu en as un, se branche comme un 4e bouton)
"""
from machine import Pin
import time

# Événements. Des entiers plutôt que des chaînes : la comparaison est plus
# rapide et n'alloue rien dans la boucle principale.
BTN_A, BTN_B, BTN_C = 0, 1, 2
SHORT, LONG, REPEAT = 0, 1, 2
TURN = 9                       # (TURN, delta) où delta vaut -1 ou +1

DEBOUNCE_MS = 25               # sous 25 ms, c'est du rebond mécanique
LONG_MS = 600                  # au-delà, l'intention est claire
REPEAT_AFTER_MS = 450          # maintien : on commence à répéter
REPEAT_EVERY_MS = 110          # puis à cette cadence

# Décodeur quadrature. L'index est (état précédent << 2) | état courant, et la
# valeur le déplacement correspondant. Les transitions impossibles valent 0,
# ce qui absorbe les rebonds au lieu de compter des crans fantômes.
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
                # L'appui long et les répétitions sont signalés au moment où
                # ils surviennent. Sans ce garde-fou, chaque maintien
                # produirait un appui court supplémentaire au relâchement.
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


class Input:
    """Toutes les entrées derrière un seul poll()."""

    def __init__(self, pin_a=32, pin_b=33, pin_c=25, clk=26, dt=27):
        # A et C se répètent quand on les maintient : c'est ce qui permet de
        # faire défiler sans l'encodeur. B ne se répète pas — son appui long
        # a un sens à lui.
        self.buttons = (
            Button(pin_a, BTN_A, repeats=True),
            Button(pin_b, BTN_B),
            Button(pin_c, BTN_C, repeats=True),
        )
        self.encoder = Encoder(clk, dt) if clk is not None else None

    def poll(self):
        """Renvoie la liste des événements survenus depuis le dernier appel."""
        out = []
        now = time.ticks_ms()
        for b in self.buttons:
            b.poll(now, out)
        if self.encoder is not None:
            self.encoder.poll(out)
        return out
