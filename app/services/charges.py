"""Les charges : des kilos partout, sur les crans de la machine.

POURQUOI DES CRANS

Les piles de la salle sont graduées en livres, par crans de 10 : 10, 20,
30… avec leur équivalent en kilos à côté (4,5 ; 9,1 ; 13,6…). Tant que
l'app raisonnait en kilos ronds, elle demandait des charges qui n'existent
sur aucune pile : 32,5 kg tombe entre 31,8 (70 lb) et 36,3 (80 lb).

Tout reste donc en kilos, à l'écran comme en base, mais chaque charge
proposée est un cran réel de la machine, converti des livres : 31,8 kg et
pas 32,5. `load_unit` dit en quoi la pile est graduée, `load_step` l'écart
entre deux crans dans cette unité.
"""
import math

LB = 0.45359237           # kilos par livre, valeur exacte par définition
UNITS = ("kg", "lb")
DEFAULT_STEP = {"kg": 2.5, "lb": 10.0}
# Une charge affichée à 0,1 kg près (31,8) retombe sur son cran exact
# (31,7515) dans cette marge ; au-delà, c'est une charge voulue, gardée telle
# quelle. Le plus petit disque d'appoint (2,5 lb, 1,1 kg) en est loin.
TOLERANCE = 0.06


def unit_of(pe):
    """L'unité dans laquelle la pile de la machine est graduée."""
    return pe.load_unit if pe.load_unit in UNITS else "kg"


def step_of(pe):
    """L'écart entre deux crans de la machine, dans l'unité de la pile."""
    if pe.load_step and pe.load_step > 0:
        return pe.load_step
    return DEFAULT_STEP[unit_of(pe)]


def factor(unit):
    return LB if unit == "lb" else 1.0


def to_kg(value, unit):
    return round((value or 0) * factor(unit), 4)


def from_kg(kg, unit):
    return (kg or 0) / factor(unit)


def step_kg(pe):
    """Un cran de la machine, en kilos (10 lb = 4,5359 kg)."""
    return to_kg(step_of(pe), unit_of(pe))


def snap(kg, pe):
    """Le cran de la machine le plus proche, en kilos.

    Un demi-cran tombe vers le bas : entre deux charges possibles, la plus
    légère garde la technique propre, et la progression remontera d'elle-même.
    """
    unit, step = unit_of(pe), step_of(pe)
    crans = math.floor(from_kg(kg, unit) / step + 0.5 - 1e-9)
    return to_kg(max(0, crans) * step, unit)


def from_display(kg, pe):
    """Une charge lue à l'écran (31,8) ramenée sur son cran exact (31,7515).

    Seul l'arrondi d'affichage est corrigé : une charge qui ne tombe sur
    aucun cran a été voulue (disque d'appoint, autre machine) et reste
    telle quelle.
    """
    kg = max(0.0, kg or 0)
    exact = snap(kg, pe)
    return exact if abs(exact - kg) <= TOLERANCE else round(kg, 4)


def shown(kg, pe):
    """La charge telle qu'elle s'affiche : en kilos, au dixième près pour une
    pile en livres (31,8), au centième sinon (33,75)."""
    return round(kg or 0, 1 if unit_of(pe) == "lb" else 2)


def number(v):
    """« 70 », « 31,8 » : la virgule française, sans zéro inutile."""
    return ("%g" % round(v or 0, 2)).replace(".", ",")


def label(kg, pe):
    """« 31,8 kg »."""
    return "{} kg".format(number(shown(kg, pe)))


def increment_steps(pe):
    """La progression, en crans : +1 en général, -1 sur une machine
    d'assistance (durcir, c'est retirer de l'assistance), 0 sans progression
    automatique."""
    if not pe.increment_kg:
        return 0
    return round(pe.increment_kg / step_kg(pe)) or (1 if pe.increment_kg > 0 else -1)


def machine_label(pe):
    """« pile en livres, crans de 10 lb (4,5 kg) »."""
    unit, step = unit_of(pe), step_of(pe)
    if unit == "lb":
        return "pile en livres, crans de {} lb ({} kg)".format(
            number(step), number(round(step_kg(pe), 1)))
    return "pile en kilos, crans de {} kg".format(number(step))


def set_machine(pe, unit, step):
    """Change la graduation d'une machine, et ce qui en découle.

    La progression avance d'un cran : l'incrément suit donc le cran, en
    gardant son signe et en restant nul sur un exercice sans progression
    automatique. La charge courante est ramenée sur un cran qui existe.
    """
    if unit not in UNITS:
        raise ValueError("unité inconnue : {!r}".format(unit))
    if not step or step <= 0:
        step = DEFAULT_STEP[unit]
    pe.load_unit, pe.load_step = unit, float(step)
    if pe.increment_kg:
        sign = 1 if pe.increment_kg > 0 else -1
        pe.increment_kg = sign * to_kg(step, unit)
    if pe.weight_kg:
        pe.weight_kg = snap(pe.weight_kg, pe)
