"""Trois boutons et un encodeur rotatif, ramenés à une file d'événements.

Le reste du firmware ne voit jamais un GPIO : il appelle poll() et reçoit des
événements déjà interprétés. Toute la logique d'anti-rebond et de filtrage
reste ici, ce qui rend les écrans testables sans matériel.

CÂBLAGE — boutons entre le GPIO et la masse, sans résistance externe : le
tirage interne est activé, un bouton relâché lit donc 1 et enfoncé 0.

    A (gauche)  GPIO 26     precedent            \
    B (select)  GPIO 27     valider / appui long  > repris de buttons.py
    C (droite)  GPIO 14     suivant              /
    encodeur    CLK 4, DT 19, poussoir 16 (marque RX2), commun au GND

L'ENCODEUR ÉMET UN DÉPLACEMENT, PAS UNE POSITION

Le firmware a longtemps été bâti autour d'un potentiomètre, et donc autour
d'un mécanisme de « rattrapage » : un potard a une position physique, et
passer d'un écran où la valeur vaut 75 % à un écran où elle vaut 30 %
aurait écrasé la seconde. Il fallait attendre que le curseur traverse la
valeur courante avant de lui rendre la main, et l'écran affichait vers où
tourner en attendant.

Un encodeur n'a pas de position. Il dit « un cran vers la droite », les
écrans appliquent ce ±1 à ce qu'ils affichent, et rien ne peut sauter. Tout
ce mécanisme a disparu avec le composant qui le rendait nécessaire — et
avec lui la calibration automatique, la zone morte et le lissage du
convertisseur, qui n'existaient que pour compenser un composant analogique.
"""
from machine import Pin, disable_irq, enable_irq
import time

# Événements. Des entiers plutôt que des chaînes : comparaison plus rapide,
# et aucune allocation dans la boucle principale.
BTN_A, BTN_B, BTN_C = 0, 1, 2
SHORT, LONG, REPEAT = 0, 1, 2
TURN = 9                       # (TURN, delta) où delta vaut -1 ou +1

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


class Encoder:
    """Encodeur rotatif en quadrature, lu par interruption.

    On compte les transitions dans l'interruption — qui doit rester
    minuscule — et on les convertit en crans dans poll().

    STEPS_PER_DETENT DÉPEND DU MODÈLE, ET SE MESURE

    Un encodeur ne fait pas forcément un cycle de quadrature complet entre
    deux crans : beaucoup ont un cran là où les deux contacts sont ouverts
    ET un autre là où ils sont fermés, ce qui n'en fait que deux.

    Mesuré sur celui-ci : 53 transitions pour un tour, 25 crans sentis sous
    le doigt, soit 2,1 — donc 2. La valeur par défaut de 4 exigeait deux
    crans par événement, et c'est ce qui faisait « marcher la molette une
    fois sur deux ». Le self-test (upload.ps1 -Test) refait la mesure et
    affiche la valeur à mettre ici.
    """

    STEPS_PER_DETENT = 2

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
        step = self.STEPS_PER_DETENT

        # Lecture-modification-écriture ATOMIQUE, et c'est indispensable.
        # _acc est écrit par l'interruption ; sans la masquer, un cran qui
        # tombe entre la lecture et la réécriture est purement écrasé. On
        # perdait donc des crans précisément pendant les rotations rapides,
        # là où les interruptions sont les plus fréquentes.
        irq = disable_irq()
        acc = self._acc
        # Division tronquée vers zéro, sans flottant : ce qui n'atteint pas
        # un cran entier reste en réserve pour le prochain appel au lieu
        # d'être arrondi et perdu.
        crans = acc // step if acc >= 0 else -((-acc) // step)
        self._acc = acc - crans * step
        enable_irq(irq)

        sens = 1 if crans > 0 else -1
        for _ in range(abs(crans)):
            out.append((TURN, sens))


class Input:
    """Toutes les entrées derrière un seul poll()."""

    def __init__(self, pin_a=26, pin_b=27, pin_c=14,
                 clk=None, dt=None, pin_push=None):
        # A et C se répètent quand on les maintient : c'est ce qui permet de
        # faire défiler sans lâcher la molette. B ne se répète pas — son
        # appui long a un sens à lui.
        buttons = [
            Button(pin_a, BTN_A, repeats=True),
            Button(pin_b, BTN_B),
            Button(pin_c, BTN_C, repeats=True),
        ]
        # Le poussoir de l'encodeur emet le MEME evenement que le bouton B.
        # Tourner puis appuyer sans deplacer la main est le geste naturel ;
        # lui donner un role a lui obligerait a en retenir un de plus pour
        # rien.
        if pin_push is not None:
            buttons.append(Button(pin_push, BTN_B))
        self.buttons = tuple(buttons)
        self.enc = (Encoder(clk, dt)
                    if clk is not None and dt is not None else None)

    def poll(self):
        """Renvoie la liste des événements survenus depuis le dernier appel."""
        out = []
        now = time.ticks_ms()
        for b in self.buttons:
            b.poll(now, out)
        if self.enc is not None:
            self.enc.poll(out)
        return out
