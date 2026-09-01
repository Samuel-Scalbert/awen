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

from machine import Pin, PWM

# Doivent correspondre a main.py.
LED_R, LED_G, LED_B = 32, 33, 13
LED_COMMON = "cathode"
DHT_PIN = 25
ENC_CLK, ENC_DT = 4, 19
CRANS_ATTENDUS = 10             # ce qu'on demande de tourner a la main
STEPS_PER_DETENT_ACTUEL = 2     # doit refleter input.py
BTN = {"A gauche": 26, "B selection": 27, "C droite": 14,
       "poussoir encodeur": 16}

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
    # pull=None EXPLICITE. Pin(n, Pin.IN) sans le preciser laisse la broche
    # avec la configuration qu'elle avait deja, et le balayage des broches
    # libres vient justement d'y activer le tirage interne : la lecture « au
    # repos » mesurerait alors ce tirage-la, pas la ligne. Les deux lignes du
    # rapport diraient toujours la meme chose, et le test perdrait tout son
    # pouvoir de discrimination sans que rien ne le signale.
    p = Pin(DHT_PIN, Pin.IN, None)
    time.sleep_ms(5)
    libre = sum(p.value() for _ in range(50))
    p = Pin(DHT_PIN, Pin.IN, Pin.PULL_UP)
    time.sleep_ms(5)
    tire = sum(p.value() for _ in range(50))
    if libre >= 45:
        return "haut", libre, tire
    if libre <= 5:
        return "bas", libre, tire
    return "instable", libre, tire


def scan_free_pins():
    """Etat au repos de GPIO 25 compare a des broches libres.

    Quand une broche reste basse malgre le tirage interne, la question
    devient : est-ce ce qui y est branche, ou la broche elle-meme ? Une
    broche libre lue avec tirage doit remonter a 1. Si 25 est la seule a
    rester a 0, le probleme la suit ; si plusieurs y restent, il faut
    chercher du cote de la platine ou d'un fil de masse qui traine.
    """
    line("=== Broches libres, pour comparaison ===")
    line("  (avec tirage interne : une broche saine et libre lit 1)")
    for gp in (DHT_PIN, 4, 16, 19):
        try:
            p = Pin(gp, Pin.IN, Pin.PULL_UP)
            time.sleep_ms(5)
            v = sum(p.value() for _ in range(20))
            note = ""
            if gp == DHT_PIN:
                note = "   <- le DHT est ici"
            elif v < 18:
                note = "   <- anormal pour une broche libre"
            line("  GPIO {:>2} : {}/20 a 1{}".format(gp, v, note))
        except Exception as e:
            line("  GPIO {:>2} : illisible — {}".format(gp, e))
    # On relache les tirages : le test suivant lit la meme broche « au
    # repos » et doit la trouver telle qu'elle est, pas telle qu'on l'a
    # laissee.
    for gp in (DHT_PIN, 4, 16, 19):
        try:
            Pin(gp, Pin.IN, None)
        except Exception:
            pass
    line("  -> GPIO {} a 0 et les autres a 20 : le defaut suit ce qui est".format(DHT_PIN))
    line("     branche la, pas la carte. Debranche les TROIS fils du module")
    line("     et relance : si GPIO {} remonte a 20, le module est mort.".format(DHT_PIN))
    line()


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
    if etat == "bas" and tire < 45:
        line("     A VERIFIER AUSSI : la resistance de 10 kOhm va-t-elle bien")
        line("     de DATA vers VCC ? Branchee de DATA vers la MASSE elle")
        line("     devient un tirage vers le bas, gagne contre les 45 kOhm")
        line("     internes, et donne exactement ce resultat — avec un")
        line("     capteur parfaitement sain.")

    try:
        import dht
    except ImportError:
        line("  le module dht n'existe pas dans ce firmware MicroPython.")
        return
    d = dht.DHT11(Pin(DHT_PIN))
    # Le composant refuse d'etre interroge plus d'une fois toutes les deux
    # secondes, et rate frequemment la premiere lecture apres l'alimentation.
    reussites = 0
    for essai in range(1, 6):
        try:
            d.measure()
            line("  essai {} : {} C, {} %".format(
                essai, d.temperature(), d.humidity()))
            reussites += 1
        except Exception as e:
            line("  essai {} : echec — {}".format(essai, e))
        time.sleep(2.5)
    # Les pistes de depannage ne s'affichent que s'il y a eu un echec.
    # Les imprimer apres cinq lectures reussies faisait douter d'un capteur
    # qui marchait parfaitement.
    if reussites == 5:
        line("  -> capteur OK.")
    elif reussites:
        line("  -> {}/5 seulement : tirage trop faible. Mets la vraie".format(reussites))
        line("     resistance de 10 kOhm entre DATA et VCC, ou raccourcis le fil.")
    else:
        line("  -> aucune lecture : mauvaise broche, DATA non reliee, ou")
        line("     resistance de tirage absente (10 kOhm entre DATA et VCC).")
    line()


def test_encoder():
    """Compte les crans reels, et verifie que les deux voies bougent.

    Un encodeur dont une seule voie est cablee « marche » a moitie : il
    compte, mais toujours dans le meme sens. Ce test regarde donc les deux
    lignes separement avant de compter.
    """
    line("=== Encodeur (CLK {}, DT {}) ===".format(ENC_CLK, ENC_DT))
    clk = Pin(ENC_CLK, Pin.IN, Pin.PULL_UP)
    dt = Pin(ENC_DT, Pin.IN, Pin.PULL_UP)
    line("  tourne EXACTEMENT {} crans vers la droite, doucement.".format(
        CRANS_ATTENDUS))
    line("  (les crans se sentent sous le doigt : compte-les)")
    line("  tu as 15 secondes...")

    quad = (0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0)
    etat = (clk.value() << 1) | dt.value()
    acc = 0
    vus_clk = set()
    vus_dt = set()
    fin = time.ticks_add(time.ticks_ms(), 15000)
    while time.ticks_diff(fin, time.ticks_ms()) > 0:
        a, b = clk.value(), dt.value()
        vus_clk.add(a)
        vus_dt.add(b)
        cur = (a << 1) | b
        if cur != etat:
            acc += quad[(etat << 2) | cur]
            etat = cur
        time.sleep_ms(1)

    line("  CLK a pris les valeurs {} ; DT {}".format(
        sorted(vus_clk), sorted(vus_dt)))
    line("  deplacement net : {} transitions".format(acc))
    if len(vus_clk) < 2:
        line("  -> CLK ne bouge jamais : fil absent, ou c'est le commun.")
    if len(vus_dt) < 2:
        line("  -> DT ne bouge jamais : fil absent, ou c'est le commun.")
    if len(vus_clk) == 2 and len(vus_dt) == 2 and abs(acc) < 4:
        line("  -> les deux voies bougent mais rien ne compte : le commun")
        line("     n'est probablement pas au GND.")
    elif acc < 0:
        line("  -> compte a l'envers : intervertis CLK et DT dans main.py.")

    # LA MESURE QUI COMPTE. Le firmware doit savoir combien de transitions
    # separent deux crans, et ca depend du modele : tous les encodeurs ne
    # font pas un cycle de quadrature complet entre deux crans. Une valeur
    # trop haute demande deux crans pour un seul evenement, et la molette
    # semble marcher une fois sur deux.
    if abs(acc) >= CRANS_ATTENDUS:
        mesure = abs(acc) / CRANS_ATTENDUS
        proche = min((4, 2, 1), key=lambda v: abs(v - mesure))
        line("  -> {:.1f} transitions par cran.".format(mesure))
        line("     Mets STEPS_PER_DETENT = {} dans input.py".format(proche))
        line("     (valeur actuelle : {})".format(STEPS_PER_DETENT_ACTUEL))
    else:
        line("  -> trop peu de transitions pour conclure : refais le test en")
        line("     tournant bien {} crans.".format(CRANS_ATTENDUS))
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
    scan_free_pins()
    test_dht()
    test_encoder()
    test_buttons()
    line("=== fin ===")


main()
