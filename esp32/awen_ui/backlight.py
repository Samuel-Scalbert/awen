"""Luminosité du rétroéclairage, en PWM sur la broche du panneau.

POURQUOI UN RÉGLAGE, ET PAS UNE VALEUR FIXE

Une palette bien contrastée ne rattrape pas un panneau trop sombre en plein
soleil, ni un panneau trop vif dans une pièce éteinte. Ce sont deux problèmes
différents : le contraste se règle dans theme.py, la quantité de lumière ici.

QUATRE NIVEAUX, PAS UN CURSEUR CONTINU

Un pourcentage libre demanderait de viser une valeur qu'on ne saurait pas
nommer. Quatre paliers se parcourent d'un appui, se reconnaissent d'un coup
d'œil, et couvrent les vraies situations : nuit, pièce éclairée, journée,
plein soleil.

ZÉRO N'EST PAS DANS LA LISTE. Un écran éteint par un appui de trop
ressemblerait à une panne, et l'utilisateur chercherait la cause au lieu du
bouton. L'extinction complète appartient à la veille, qui a une raison de la
déclencher et sait la défaire.
"""
from machine import PWM, Pin

# Palier de secours si le fichier est absent ou illisible : le maximum. Un
# afficheur qui démarre trop lumineux se remarque et se corrige ; un
# afficheur qui démarre trop sombre passe pour cassé.
LEVELS = (15, 40, 70, 100)
DEFAULT = 100

# 1 kHz : au-delà du scintillement perceptible, en dessous de la fréquence où
# le transistor du panneau commencerait à chauffer pour rien.
FREQ = 1000
DUTY_MAX = 1023

_STORE = "awen_backlight.txt"


def load():
    """Le niveau enregistré, ou le maximum si rien n'a jamais été choisi."""
    try:
        with open(_STORE) as f:
            value = int(f.read().strip())
        return value if value in LEVELS else DEFAULT
    except (OSError, ValueError):
        return DEFAULT


def save(level):
    """Un échec d'écriture ne doit pas priver d'affichage. Voir theme.save()."""
    try:
        with open(_STORE, "w") as f:
            f.write(str(level))
        return True
    except OSError:
        return False


class Backlight:
    """Le rétroéclairage, avec son niveau courant et une extinction séparée.

    `level` reste la valeur choisie même écran éteint : la veille coupe la
    lumière sans oublier à quoi la ramener au réveil. Confondre les deux
    ferait revenir l'écran à un niveau arbitraire après chaque absence.
    """

    def __init__(self, pin_no, level=None):
        self.pwm = PWM(Pin(pin_no), freq=FREQ)
        self.level = load() if level is None else level
        self.on = True
        self._apply()

    def _apply(self):
        pct = self.level if self.on else 0
        self.pwm.duty(pct * DUTY_MAX // 100)

    def set_level(self, pct):
        self.level = pct
        self._apply()

    def next_level(self):
        """Palier suivant, en boucle. Renvoie le nouveau niveau."""
        i = LEVELS.index(self.level) if self.level in LEVELS else len(LEVELS) - 1
        self.set_level(LEVELS[(i + 1) % len(LEVELS)])
        return self.level

    def wake(self):
        self.on = True
        self._apply()

    def sleep(self):
        self.on = False
        self._apply()


class NoBacklight:
    """Quand la broche n'est pas câblée : tout marche, rien ne s'allume.

    Évite de parsemer le reste du firmware de tests d'existence pour un
    périphérique optionnel.
    """

    level = DEFAULT
    on = True

    def set_level(self, pct):
        self.level = pct

    def next_level(self):
        i = LEVELS.index(self.level) if self.level in LEVELS else len(LEVELS) - 1
        self.level = LEVELS[(i + 1) % len(LEVELS)]
        return self.level

    def wake(self):
        self.on = True

    def sleep(self):
        self.on = False


def make(pin=None):
    if pin is None:
        return NoBacklight()
    try:
        return Backlight(pin)
    except Exception:
        # Une broche déjà prise par le pilote d'écran, ou inexistante : mieux
        # vaut un afficheur sans réglage qu'un afficheur qui ne démarre pas.
        return NoBacklight()
