"""Les charges : des kilos partout, sur les crans de la machine.

POURQUOI DES CRANS

Les piles de la salle sont graduées en livres, par crans de 10 : 10, 20,
30… avec leur équivalent en kilos à côté (4,5 ; 9,1 ; 13,6…). Tant que
l'app raisonnait en kilos ronds, elle demandait des charges qui n'existent
sur aucune pile : 32,5 kg tombe entre 31,8 (70 lb) et 36,3 (80 lb).

Tout reste donc en kilos, à l'écran comme en base, mais chaque charge
proposée est un cran réel de la machine. `load_unit` dit en quoi la pile est
graduée, `load_step` l'écart entre deux crans dans cette unité (10 lb sur
les machines guidées, 5 lb sur les poulies).

CE QUI EST ÉCRIT SUR LA MACHINE

La base garde la masse exacte d'un cran (90 lb = 40,8233 kg), mais l'écran
montre l'étiquette de la pile, celle qu'on lit en salle : livres × 0,45,
arrondi à l'entier sur les crans de 10 lb (40 lb : 18, 90 lb : 41), au
dixième sur les poulies par crans de 5 lb (35 lb : 15,8 ; 50 lb : 22,5).
Règle relevée sur les séries du 20/10/2026, notées telles qu'écrites sur
les machines.

LE POIDS D'APPOINT

Certaines machines ont, en plus de la pile, un petit poids qu'on ajoute à
n'importe quel cran : 7,5 lb sur la presse triceps, étiqueté 3,4. « Il y
avait du poids en plus du cran sur la machine, 3,4 kg » (21/10/2026). Les
charges possibles sont alors chaque cran, avec ou sans l'appoint ; une
étiquette se lit comme la somme des deux (54 + 3,4 = 57,4). `load_extra` le
porte, dans l'unité de la pile, et vaut 0 sur une machine qui n'en a pas.
"""
import math

LB = 0.45359237           # kilos par livre, valeur exacte par définition
UNITS = ("kg", "lb")
DEFAULT_STEP = {"kg": 2.5, "lb": 10.0}
# Une charge affichée à 0,1 kg près (31,8) retombe sur son cran exact
# (31,7515) dans cette marge ; au-delà, c'est une charge voulue, gardée telle
# quelle. Le plus petit disque d'appoint (2,5 lb, 1,1 kg) en est loin.
TOLERANCE = 0.06
# Kilos par livre selon les étiquettes des piles de la salle.
ETIQUETTE = 0.45


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


def extra_of(pe):
    """Le poids d'appoint, dans l'unité de la pile ; 0 s'il n'y en a pas."""
    extra = getattr(pe, "load_extra", None)
    return extra if extra and extra > 0 else 0.0


def appoint(pe):
    """L'étiquette du poids d'appoint : 7,5 lb s'y lit 3,4."""
    extra = extra_of(pe)
    if unit_of(pe) == "lb":
        return _arrondi(extra * ETIQUETTE, 1)
    return extra


def step_kg(pe):
    """Un cran de la machine, en kilos (10 lb = 4,5359 kg)."""
    return to_kg(step_of(pe), unit_of(pe))


def snap(kg, pe):
    """Le cran de la machine le plus proche, en kilos.

    Un demi-cran tombe vers le bas : entre deux charges possibles, la plus
    légère garde la technique propre, et la progression remontera d'elle-même.
    """
    unit, step = unit_of(pe), step_of(pe)
    v = from_kg(kg, unit)
    crans = math.floor(v / step + 0.5 - 1e-9)
    best = max(0, crans) * step
    extra = extra_of(pe)
    if extra:
        # Le même calcul sur la pile chargée de l'appoint ; à égale distance,
        # sans l'appoint.
        avec = max(0, math.floor((v - extra) / step + 0.5 - 1e-9)) * step + extra
        if abs(avec - v) < abs(best - v) - 1e-9:
            best = avec
    return to_kg(best, unit)


def decimales(pe):
    """Entier sur les crans de 10 lb, dixième sur les poulies, centième en kilos."""
    if unit_of(pe) == "lb":
        return 0 if step_of(pe) >= 10 else 1
    return 2


def _arrondi(v, dec):
    """Arrondi « à l'école », comme les étiquettes : 40,5 donne 41."""
    k = 10 ** dec
    return math.floor(v * k + 0.5 + 1e-9) / k


def _etiquette(crans, pe):
    """L'étiquette du cran n°crans d'une pile en livres."""
    return _arrondi(max(0, crans) * step_of(pe) * ETIQUETTE, decimales(pe))


def _cran_lu(valeur, pe):
    """Le cran dont l'étiquette est `valeur`, ou None."""
    crans = math.floor(valeur / ETIQUETTE / step_of(pe) + 0.5)
    if abs(_etiquette(crans, pe) - valeur) <= 0.5 * 10 ** -decimales(pe) + 1e-9:
        return crans
    return None


def from_display(valeur, pe):
    """Une charge lue sur la machine (41) ramenée sur son cran exact (90 lb,
    40,8233 kg). Avec l'appoint, 57,4 se lit 54 + 3,4 : 120 lb plus 7,5.

    Une valeur qui n'est l'étiquette d'aucun cran a été voulue (disque
    d'appoint, autre machine) : elle est gardée telle quelle.
    """
    valeur = max(0.0, valeur or 0)
    if unit_of(pe) == "lb":
        crans = _cran_lu(valeur, pe)
        if crans is not None:
            return to_kg(crans * step_of(pe), "lb")
        if extra_of(pe) and valeur >= appoint(pe):
            crans = _cran_lu(round(valeur - appoint(pe), 4), pe)
            if crans is not None:
                return to_kg(crans * step_of(pe) + extra_of(pe), "lb")
        return round(valeur, 4)
    exact = snap(valeur, pe)
    return exact if abs(exact - valeur) <= TOLERANCE else round(valeur, 4)


def shown(kg, pe):
    """La charge telle qu'elle s'affiche.

    Sur un cran exact d'une pile en livres : son étiquette (90 lb : 41). Une
    charge notée avant, hors cran, s'affiche telle qu'elle a été tapée.
    En kilos, au centième (33,75).
    """
    kg = kg or 0
    if unit_of(pe) == "lb" and abs(snap(kg, pe) - kg) <= TOLERANCE:
        v, extra = from_kg(kg, "lb"), extra_of(pe)
        crans = v / step_of(pe)
        if abs(crans - round(crans)) < 1e-3 or not extra:
            return _etiquette(round(crans), pe)
        base = _etiquette(round((v - extra) / step_of(pe)), pe)
        return round(base + appoint(pe), 2)
    return round(kg, 1 if unit_of(pe) == "lb" else 2)


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
    """« pile en livres, crans de 10 lb »."""
    unit, step = unit_of(pe), step_of(pe)
    if unit == "lb":
        texte = "pile en livres, crans de {} lb".format(number(step))
    else:
        texte = "pile en kilos, crans de {} kg".format(number(step))
    if extra_of(pe):
        texte += ", appoint de {} {}".format(number(extra_of(pe)), unit)
        if unit == "lb":
            texte += " ({})".format(number(appoint(pe)))
    return texte


def stepper(pe):
    """Ce que le script de la séance doit savoir pour avancer d'un cran et
    afficher l'étiquette qui va avec."""
    lb = unit_of(pe) == "lb"
    return {"grid": unit_of(pe), "step": step_of(pe),
            "factor": ETIQUETTE if lb else 1.0, "dec": decimales(pe),
            "extra": appoint(pe)}


def set_machine(pe, unit, step, extra=None):
    """Change la graduation d'une machine, et ce qui en découle.

    La progression avance d'un cran : l'incrément suit donc le cran, en
    gardant son signe et en restant nul sur un exercice sans progression
    automatique. La charge courante est ramenée sur un cran qui existe.
    `extra` règle le poids d'appoint (0 : aucun) ; None le laisse tel quel.
    """
    if unit not in UNITS:
        raise ValueError("unité inconnue : {!r}".format(unit))
    if not step or step <= 0:
        step = DEFAULT_STEP[unit]
    pe.load_unit, pe.load_step = unit, float(step)
    if extra is not None:
        pe.load_extra = float(extra) if extra > 0 else 0.0
    if pe.increment_kg:
        sign = 1 if pe.increment_kg > 0 else -1
        pe.increment_kg = sign * to_kg(step, unit)
    if pe.weight_kg:
        pe.weight_kg = snap(pe.weight_kg, pe)
