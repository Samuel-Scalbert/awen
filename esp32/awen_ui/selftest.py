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

from machine import Pin, PWM, time_pulse_us

# Doivent correspondre a main.py.
LED_R, LED_G, LED_B = 32, 33, 13
LED_COMMON = "cathode"
DHT_PIN = 25
ENC_CLK, ENC_DT = 4, 19
# HC-SR04. ECHO sort du 5 V : il DOIT passer par un pont diviseur avant
# GPIO 34 (10k vers ECHO, 20k vers GND). En direct, la broche prend 5 V sur
# une entree prevue pour 3,3.
US_TRIG, US_ECHO = 15, 34
# Retroeclairage de l'ecran. Il vit normalement dans tft_setup.py, qui est
# sur la carte et pas dans ce depot ; on le repique ici parce qu'un test doit
# pouvoir eteindre l'ecran sans initialiser tout le pilote.
BACKLIGHT = 22
CRANS_ATTENDUS = 10             # ce qu'on demande de tourner a la main
STEPS_PER_DETENT_ACTUEL = 4     # doit refleter input.py
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

    # LU PAR INTERRUPTION, comme input.py — et surtout PAS en echantillonnant
    # en Python. Une boucle sleep_ms(1) ne tient pas la cadence d'un encodeur
    # qu'on tourne a la main : elle rate des etats, le decodeur absorbe les
    # transitions devenues impossibles, et le compte s'effondre. Ce test
    # annoncait « 4 transitions » pour 10 crans reellement tournes. Mesurer
    # autrement que le firmware, c'est mesurer autre chose que le firmware.
    quad = (0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0)
    etat = [(clk.value() << 1) | dt.value()]
    acc = [0]
    brutes = [0]
    vus_clk = set()
    vus_dt = set()

    def _irq(_pin):
        a, b = clk.value(), dt.value()
        cur = (a << 1) | b
        if cur != etat[0]:
            brutes[0] += 1
            acc[0] += quad[(etat[0] << 2) | cur]
            etat[0] = cur

    trig = Pin.IRQ_RISING | Pin.IRQ_FALLING
    clk.irq(trigger=trig, handler=_irq)
    dt.irq(trigger=trig, handler=_irq)

    fin = time.ticks_add(time.ticks_ms(), 15000)
    while time.ticks_diff(fin, time.ticks_ms()) > 0:
        vus_clk.add(clk.value())
        vus_dt.add(dt.value())
        time.sleep_ms(5)

    # On coupe les interruptions : les laisser vivre apres le test ferait
    # tourner ce handler pendant les tests suivants.
    clk.irq(handler=None)
    dt.irq(handler=None)

    acc, brutes = acc[0], brutes[0]
    line("  CLK a pris les valeurs {} ; DT {}".format(
        sorted(vus_clk), sorted(vus_dt)))
    line("  {} transitions vues, deplacement net : {}".format(brutes, acc))
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


def _mesure_us(trig, echo, timeout_us=40000):
    """Une mesure brute, en microsecondes d'aller-retour. -1 si rien.

    time_pulse_us renvoie -2 si l'echo n'est jamais monte (module muet ou
    TRIG non cable) et -1 s'il n'est jamais redescendu (obstacle trop loin,
    ou ECHO bloque en haut). On distingue les deux : ils n'ont pas la meme
    cause et pas le meme depannage.
    """
    trig.value(0)
    time.sleep_us(5)
    trig.value(1)
    time.sleep_us(10)          # la salve se declenche sur 10 us exactement
    trig.value(0)
    try:
        return time_pulse_us(echo, 1, timeout_us)
    except OSError:
        return -1


def test_ultrason():
    line("=== HC-SR04 (TRIG {}, ECHO {}) ===".format(US_TRIG, US_ECHO))
    trig = Pin(US_TRIG, Pin.OUT)
    echo = Pin(US_ECHO, Pin.IN)

    # ETAT DE LA LIGNE AVANT DE PULSER. GPIO 34 n'a aucun tirage interne
    # (34-39 en sont depourvues), donc sans rien au bout elle flotte et prend
    # des valeurs au hasard. Avec le pont diviseur en place, l'ECHO au repos
    # est tenu bas : une ligne STABLE a 0 prouve que quelque chose est
    # branche, une ligne qui papillonne prouve le contraire. Sans ce releve,
    # « aucun echo » ne distingue pas un capteur absent d'un capteur muet.
    hauts = sum(echo.value() for _ in range(50))
    if hauts == 0:
        # ATTENTION a ne pas surinterpreter : c'est le 2k du pont qui tient
        # la ligne basse. Ce releve prouve que le DIVISEUR est cable, pas que
        # le capteur est alimente ni que TRIG est relie.
        etat = "bas et stable (le pont diviseur est en place)"
    elif hauts == 50:
        etat = "haut et stable (TRIG et ECHO inverses ?)"
    else:
        etat = "instable, {}/50 a 1 — LA LIGNE FLOTTE, rien n'est cable".format(hauts)
    line("  ligne ECHO au repos : {}".format(etat))

    line("  pointe le capteur vers un mur, puis passe la main devant.")
    line("  10 mesures, une toutes les 400 ms...")
    lues, muettes, perdues = [], 0, 0
    for i in range(10):
        d = _mesure_us(trig, echo)
        if d == -2:
            muettes += 1
            line("  {:2}. aucun echo".format(i + 1))
        elif d < 0:
            perdues += 1
            line("  {:2}. hors portee".format(i + 1))
        else:
            # 58 us par centimetre aller-retour : le son fait 343 m/s, donc
            # 29,1 us/cm, double par le trajet retour.
            cm = d / 58
            lues.append(cm)
            line("  {:2}. {:.1f} cm".format(i + 1, cm))
        time.sleep_ms(400)

    if lues:
        line("  -> {}/10 mesures, de {:.1f} a {:.1f} cm.".format(
            len(lues), min(lues), max(lues)))
        if max(lues) - min(lues) < 1:
            line("     La distance ne bouge pas : as-tu bien passe la main ?")
        else:
            line("     Capteur OK.")
    elif muettes and hauts not in (0, 50):
        line("  -> AUCUN ECHO, et la ligne flotte : le capteur n'est tout")
        line("     simplement pas branche. Rien d'autre a chercher.")
    elif muettes:
        line("  -> AUCUN ECHO, mais le pont diviseur est bien la. Le capteur")
        line("     ne recoit pas l'ordre, ou pas de courant :")
        line("     - TRIG relie a GPIO {} ? C'est la cause n1 : sans lui le".format(US_TRIG))
        line("       capteur ne tire jamais, et ECHO reste bas pour toujours.")
        line("     - VCC sur VIN (5 V), pas sur 3V3 : il decroche sous 4,5 V.")
        line("     - TRIG et ECHO inverses ? GPIO 34 est en ENTREE SEULE, il")
        line("       ne peut pas declencher : l'inversion est invisible ici.")
        line("     - GND du capteur commun avec celui de la carte.")
    else:
        line("  -> echo bloque en haut : verifie le pont diviseur sur ECHO.")
    line()


def _led_channels():
    """Les trois voies PWM de la LED, ou None si elle n'existe pas."""
    invert = LED_COMMON == "anode"
    try:
        return ({n: PWM(Pin(pp), freq=1000, duty=(DUTY_MAX if invert else 0))
                 for n, pp in (("r", LED_R), ("g", LED_G), ("b", LED_B))},
                DUTY_MAX if invert else 0,          # eteint
                0 if invert else DUTY_MAX)          # allume
    except Exception:
        return None, 0, 0


def test_veille():
    """Ecran et LED s'eteignent ENSEMBLE, et se rallument ensemble.

    C'est le geste que la detection de presence declenchera. Le verifier a la
    main d'abord evite de deboguer deux choses en meme temps : si l'ecran
    reste allume ici, ce n'est pas le capteur qu'il faudra soupconner.

    La LED est le point facile a oublier. Un afficheur "eteint" dont la LED
    continue de briller dans le noir n'est pas eteint — c'est meme la seule
    chose qu'on verra encore.
    """
    line("=== Veille : ecran + LED (retroeclairage GPIO {}) ===".format(BACKLIGHT))
    bl = Pin(BACKLIGHT, Pin.OUT)
    ch, off, on = _led_channels()

    line("  allumage : ecran + LED bleue, 3 secondes...")
    bl.value(1)
    if ch:
        ch["b"].duty(on)
    time.sleep(3)

    line("  EXTINCTION : les DEUX doivent s'eteindre, 4 secondes...")
    bl.value(0)
    if ch:
        for c in ch.values():
            c.duty(off)
    time.sleep(4)

    line("  rallumage.")
    bl.value(1)
    if ch:
        ch["b"].duty(on)
    time.sleep(2)
    if ch:
        for c in ch.values():
            c.duty(off)
            c.deinit()

    line("  -> l'ecran est reste allume ? Le retroeclairage n'est pas sur")
    line("     GPIO {}, ou il est cable en direct sur le 3V3.".format(BACKLIGHT))
    line("  -> la LED est restee allumee ? Voir la section LED plus haut.")
    line()


def test_distance_bureau():
    """Releve la distance a laquelle tu te tiens vraiment, assis.

    Le seuil de presence ne se devine pas depuis un bureau qu'on ne voit
    pas : il depend de ou est pose le capteur, de la profondeur du plan de
    travail et de la facon de s'asseoir. On mesure, on ne suppose pas.
    """
    line("=== Distance de travail ===")
    trig = Pin(US_TRIG, Pin.OUT)
    echo = Pin(US_ECHO, Pin.IN)
    line("  ASSIEDS-TOI normalement devant l'ecran, comme tous les jours,")
    line("  et ne bouge plus. 15 secondes de mesure...")
    time.sleep(3)

    lues = []
    for _ in range(30):
        d = _mesure_us(trig, echo)
        if d > 0:
            lues.append(d / 58)
        time.sleep_ms(400)

    if len(lues) < 5:
        line("  -> trop peu de mesures valides ({}) pour conclure.".format(
            len(lues)))
        line()
        return

    lues.sort()
    med = lues[len(lues) // 2]
    line("  {} mesures : de {:.0f} a {:.0f} cm, mediane {:.0f} cm.".format(
        len(lues), lues[0], lues[-1], med))

    # Le seuil se pose au-dessus de la plus grande distance observee assis,
    # avec de la marge pour un dos qui se redresse ou une chaise qui recule.
    # Trop juste, l'ecran s'eteindrait pendant qu'on travaille — le pire
    # defaut possible pour cette fonction.
    seuil = int((lues[-1] * 1.5 + 9) // 10 * 10)
    line("  -> Seuil conseille : PRESENCE_CM = {}".format(seuil))
    line("     (50 % au-dessus de ta position la plus reculee)")
    if lues[-1] - lues[0] > 40:
        line("  -> mesures tres dispersees : le capteur voit sans doute autre")
        line("     chose que toi par moments (chaise, mur, ecran). Reoriente-le.")
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
    test_ultrason()
    test_distance_bureau()
    test_veille()
    test_buttons()
    line("=== fin ===")


main()
