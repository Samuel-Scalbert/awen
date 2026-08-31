"""La LED d'état : une couleur par écran, un clignotement pour alerter.

QUELLE LED TU AS

  4 broches  LED RGB classique : R, V, B et un commun. C'est le cas ici.
             Trois GPIO en PWM, et TROIS RESISTANCES — voir plus bas.
  3 broches  soit une WS2812 (donnees, +, masse), soit une bicolore.

COMMUN A L'ANODE OU A LA CATHODE ?

La patte la plus longue est le commun. Pour trancher :

  - commun a la CATHODE : le commun va au GND, une couleur s'allume quand
    sa broche passe au niveau haut. C'est le cas le plus repandu.
  - commun a l'ANODE : le commun va au 3V3, une couleur s'allume quand sa
    broche passe au niveau BAS — tout est inverse.

Test en dix secondes : relie le commun au GND, puis touche une patte de
couleur au 3V3 a travers une resistance de 220 ohms. Si elle s'allume,
c'est une cathode commune. Sinon, refais l'essai avec le commun au 3V3 et
la patte de couleur au GND.

Si les couleurs sortent a l'envers — l'ecran d'accueil devrait etre orange
et sort cyan — c'est que le type est mal declare dans main.py.

LES RESISTANCES NE SONT PAS FACULTATIVES

Une LED sans limitation tire tout ce qu'elle peut. Un GPIO d'ESP32 donne
12 mA en confort et 40 mA en absolu : sans resistance, la LED et la sortie
se degradent, parfois lentement. 220 ohms sur CHAQUE patte de couleur.

Le rouge s'allume a une tension plus basse que le vert et le bleu : a
resistances egales il domine. GAINS le corrige.
"""
from machine import Pin, PWM

FREQ = 1000              # au-dessus de la persistance retinienne
DUTY_MAX = 1023          # PWM 10 bits, resolution par defaut de l'ESP32

# Deux luminosites, parce que les deux composants n'ont rien a voir : une
# LED nue derriere 220 ohms tire quelques milliamperes et reste discrete,
# une WS2812 a fond est eblouissante a un metre.
BRIGHT_RGB = 70
BRIGHT_WS = 10

# Un rouge a la meme intensite electrique parait bien plus vif qu'un bleu :
# on le brise pour que « orange » sorte orange et pas rouge.
GAINS = (60, 100, 100)


class RgbPwm:
    """LED RGB a 4 broches, une PWM par couleur."""

    def __init__(self, pin_r, pin_g, pin_b, common="cathode"):
        self.ch = [PWM(Pin(p), freq=FREQ, duty=0)
                   for p in (pin_r, pin_g, pin_b)]
        # Avec un commun a l'anode, la couleur s'allume au niveau bas : le
        # rapport cyclique doit etre inverse, sinon la LED est allumee quand
        # on la croit eteinte et l'ecran d'accueil reste blanc en permanence.
        self.invert = (common == "anode")
        self.last = None
        self.show(None)

    def show(self, rgb):
        if rgb == self.last:
            return                      # rien a reecrire
        self.last = rgb
        vals = (0, 0, 0) if rgb is None else rgb
        for chan, v, gain in zip(self.ch, vals, GAINS):
            duty = v * DUTY_MAX * BRIGHT_RGB * gain // (255 * 100 * 100)
            chan.duty(DUTY_MAX - duty if self.invert else duty)


class Ws2812:
    """LED adressable a 3 broches : une couleur arbitraire sur un fil."""

    def __init__(self, pin_no):
        import neopixel
        self.np = neopixel.NeoPixel(Pin(pin_no, Pin.OUT), 1)
        self.last = None

    def show(self, rgb):
        if rgb == self.last:
            return
        self.last = rgb
        self.np[0] = ((0, 0, 0) if rgb is None
                      else tuple(c * BRIGHT_WS // 100 for c in rgb))
        self.np.write()


class NoLed:
    """Aucune LED cablee. Tout le firmware appelle show() sans se poser de
    question : c'est ici qu'on absorbe l'absence, pas dans chaque ecran."""

    def show(self, rgb):
        pass


def make(kind="rgb", pin=None, pin_r=None, pin_g=None, pin_b=None,
         common="cathode"):
    """Fabrique la LED decrite, ou un objet inerte si elle manque.

    Une LED absente ou mal cablee ne doit pas empecher l'afficheur de
    demarrer : c'est un confort, pas une dependance.
    """
    try:
        if kind == "ws2812":
            return Ws2812(pin) if pin is not None else NoLed()
        if None in (pin_r, pin_g, pin_b):
            return NoLed()
        return RgbPwm(pin_r, pin_g, pin_b, common)
    except Exception as e:
        print("led:", e)
        return NoLed()
