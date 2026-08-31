"""Test du materiel, canal par canal. A lancer a la main, pas au demarrage.

    mpremote connect COM5 run selftest.py

Il n'affiche rien a l'ecran : tout passe par la console serie. L'idee est
de savoir CE QUI marche avant de chercher pourquoi le reste ne marche pas —
un « pas de capteur » sur l'accueil ne dit pas si le DHT est mal cable, sur
la mauvaise broche, ou simplement lent a repondre.

La LED est poussee a pleine puissance ici, contrairement au firmware qui la
bride : un test doit lever le doute, pas menager les yeux.
"""
import time

from machine import ADC, Pin, PWM

# Doivent correspondre a main.py.
LED_R, LED_G, LED_B = 32, 33, 13
LED_COMMON = "cathode"
DHT_PIN = 25
POT_PIN = 34
BTN = {"A gauche": 26, "B selection": 27, "C droite": 14}

DUTY_MAX = 1023


def line(s=""):
    print(s)


def test_led():
    line("=== LED ===")
    invert = LED_COMMON == "anode"
    off = DUTY_MAX if invert else 0
    on = 0 if invert else DUTY_MAX
    try:
        ch = {n: PWM(Pin(p), freq=1000, duty=off)
              for n, p in (("rouge", LED_R), ("verte", LED_G), ("bleue", LED_B))}
    except Exception as e:
        line("  impossible d'initialiser : {}".format(e))
        return
    line("  commun declare : {}".format(LED_COMMON))
    for name, c in ch.items():
        line("  {} (GPIO {}) : 2 secondes...".format(
            name, {"rouge": LED_R, "verte": LED_G, "bleue": LED_B}[name]))
        c.duty(on)
        time.sleep(2)
        c.duty(off)
    line("  les trois ensemble (doit donner du blanc) : 2 secondes...")
    for c in ch.values():
        c.duty(on)
    time.sleep(2)
    for c in ch.values():
        c.duty(off)
        c.deinit()
    line("  -> une couleur qui n'est pas apparue = patte grillee, mal cablee,")
    line("     ou resistance absente lors d'un essai precedent.")
    line("  -> AUCUNE couleur avec le commun au GND : essaie LED_COMMON =")
    line('     "anode" et le commun au 3V3.')
    line()


def probe_data_line():
    """Deux lectures qui, ensemble, designent le coupable.

    SANS tirage interne, au repos : un DHT11 alimente tient sa ligne DATA au
    niveau haut par sa propre resistance.

      haut      le cablage porte et le capteur est alimente ; le probleme
                est dans le dialogue lui-meme.
      bas       rien ne tire la ligne vers le haut.
      instable  la ligne flotte : DATA n'est reliee a rien.

    AVEC le tirage interne (~45 kOhm), on tranche le cas « bas », qui a deux
    causes opposees :

      redevient haut   personne ne tire vers le bas. Le module n'est donc pas
                       alimente — mauvais contact du 3V3 ou de la masse sur
                       la platine, le cas le plus frequent — ou il n'a pas
                       de resistance de tirage.
      reste bas        quelque chose tire activement vers la masse et gagne
                       contre 45 kOhm. C'est un court-circuit : capteur mort,
                       ou fil DATA en realite sur la masse.

    Sans ce second essai, les deux se presentent identiquement et on cherche
    un capteur mort alors qu'un fil est simplement mal enfonce.
    """
    p = Pin(DHT_PIN, Pin.IN)
    libre = sum(p.value() for _ in range(50))
    p = Pin(DHT_PIN, Pin.IN, Pin.PULL_UP)
    time.sleep_ms(5)
    tire = sum(p.value() for _ in range(50))
    if libre >= 45:
        return "haut", libre, tire
    if libre <= 5:
        return "bas", libre, tire
    return "instable", libre, tire


def test_dht():
    line("=== DHT11 (GPIO {}) ===".format(DHT_PIN))
    etat, libre, tire = probe_data_line()
    line("  ligne DATA au repos    : {} ({}/50 a 1)".format(etat, libre))
    line("  avec tirage interne    : {}/50 a 1".format(tire))
    if etat == "bas":
        if tire >= 45:
            line("  -> LE MODULE N'EST PAS ALIMENTE. Personne ne tire vers le")
            line("     bas : la ligne remonte des qu'on la tire vers le haut.")
            line("     Le capteur n'est donc pas mort — c'est le 3V3 ou la")
            line("     masse qui n'arrive pas. Reenfonce les trois fils, et")
            line("     verifie que la rangee de la platine est bien alimentee.")
        else:
            line("  -> COURT-CIRCUIT VERS LA MASSE. Quelque chose tire la")
            line("     ligne vers le bas et gagne contre 45 kOhm. Soit le fil")
            line("     DATA est en fait sur la masse, soit le capteur est HS.")
            line("     Debranche le module et relance : si la ligne devient")
            line("     instable, c'est bien le capteur.")
    elif etat == "instable":
        line("  -> la ligne flotte : DATA n'est reliee a rien.")

    try:
        import dht
    except ImportError:
        line("  le module dht n'existe pas dans ce firmware MicroPython.")
        return
    d = dht.DHT11(Pin(DHT_PIN))
    # Le composant refuse d'etre interroge plus d'une fois toutes les deux
    # secondes, et rate frequemment la premiere lecture apres l'alimentation.
    for essai in range(1, 6):
        try:
            d.measure()
            line("  essai {} : {} C, {} %".format(
                essai, d.temperature(), d.humidity()))
        except Exception as e:
            line("  essai {} : echec — {}".format(essai, e))
        time.sleep(2.5)
    line("  -> ETIMEDOUT a chaque fois : mauvaise broche, DATA non reliee,")
    line("     ou resistance de tirage absente (10 kOhm entre DATA et 3V3).")
    line("  -> checksum : cablage correct mais signal bruite ; rapproche le")
    line("     module ou raccourcis le fil.")
    line()


def test_pot():
    line("=== Potentiometre (GPIO {}) ===".format(POT_PIN))
    adc = ADC(Pin(POT_PIN))
    adc.atten(ADC.ATTN_11DB)
    line("  tourne-le a fond dans les deux sens pendant 8 secondes...")
    lo, hi = 4095, 0
    fin = time.ticks_add(time.ticks_ms(), 8000)
    while time.ticks_diff(fin, time.ticks_ms()) > 0:
        v = adc.read()
        lo = min(lo, v)
        hi = max(hi, v)
        time.sleep_ms(50)
    span = hi - lo
    line("  lu : {} a {}  (course de {} points sur 4095)".format(lo, hi, span))
    if span < 300:
        line("  -> quasi immobile : le curseur n'est relie a rien, ou le")
        line("     potard n'est plus la du tout.")
    elif span < 1500:
        line("  -> COURSE TROP FAIBLE. Un potard cable entre 3V3 et GND")
        line("     balaie pres de 3800 points. Verifie que ses DEUX pattes")
        line("     exterieures sont bien l'une au 3V3 et l'autre au GND, et")
        line("     que le fil du milieu part vers GPIO {}.".format(POT_PIN))
        line("     Une extremite en l'air donne exactement ce resultat.")
    else:
        line("  -> course correcte.")
    line()


def test_buttons():
    line("=== Boutons ===")
    pins = {n: Pin(p, Pin.IN, Pin.PULL_UP) for n, p in BTN.items()}
    line("  appuie sur les trois, un par un, pendant 10 secondes...")
    vus = set()
    fin = time.ticks_add(time.ticks_ms(), 10000)
    while time.ticks_diff(fin, time.ticks_ms()) > 0:
        for n, p in pins.items():
            if not p.value() and n not in vus:
                vus.add(n)
                line("  {} : OK".format(n))
        time.sleep_ms(20)
    for n in BTN:
        if n not in vus:
            line("  {} : jamais vu".format(n))
    line()


def main():
    import gc
    gc.collect()
    line("memoire libre : {}".format(gc.mem_free()))
    line()
    test_led()
    test_dht()
    test_pot()
    test_buttons()
    line("=== fin ===")


main()
