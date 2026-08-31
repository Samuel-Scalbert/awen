"""La LED d'état : une couleur par écran, un clignotement pour alerter.

QUELLE LED TU AS

Une LED à trois broches est presque toujours une WS2812 (« NeoPixel ») :
données, +5 V, masse. Elle contient son propre contrôleur et donne les
16 millions de couleurs sur un seul fil de données — c'est ce que ce module
pilote.

L'autre possibilité à trois broches est une LED bicolore (deux anodes et une
cathode commune), qui ne fait que deux teintes et leur mélange. Pour la
distinguer : une WS2812 a une puce carrée visible dans le boîtier, et son
module porte souvent « DIN » et « DO » sérigraphiés. Si c'est une bicolore,
mets LED_KIND = "bicolor" dans main.py et cable les deux anodes.

LA LUMINOSITÉ EST BRIDÉE

Une WS2812 à pleine puissance est éblouissante à un mètre et tire 60 mA.
Sur un bureau, dans le noir, un dixième suffit largement — et laisse de la
marge à l'alimentation de la carte.
"""
from machine import Pin

BRIGHTNESS = 10          # pourcents ; au-delà c'est aveuglant de près


class Rgb:
    """WS2812 : une couleur arbitraire sur un seul fil."""

    def __init__(self, pin_no):
        import neopixel
        self.np = neopixel.NeoPixel(Pin(pin_no, Pin.OUT), 1)
        self.last = None

    def show(self, rgb):
        """rgb est un triplet 0-255. None éteint la LED."""
        if rgb == self.last:
            return                      # rien à réécrire sur le fil
        self.last = rgb
        if rgb is None:
            self.np[0] = (0, 0, 0)
        else:
            self.np[0] = tuple(c * BRIGHTNESS // 100 for c in rgb)
        self.np.write()


class Bicolor:
    """LED bicolore : deux anodes, une cathode commune.

    On ne peut rendre que trois états visibles. On rapproche donc chaque
    couleur demandée de ce que la LED sait faire, plutôt que d'afficher
    n'importe quoi : c'est la composante dominante qui décide.
    """

    def __init__(self, pin_a, pin_b):
        self.a = Pin(pin_a, Pin.OUT)
        self.b = Pin(pin_b, Pin.OUT)
        self.last = None

    def show(self, rgb):
        if rgb == self.last:
            return
        self.last = rgb
        if rgb is None:
            self.a.value(0)
            self.b.value(0)
            return
        r, g, _ = rgb
        self.a.value(1 if r > 60 else 0)
        self.b.value(1 if g > 60 else 0)


class NoLed:
    """Aucune LED câblée. Tout le firmware appelle show() sans se poser
    de question : c'est ici qu'on absorbe l'absence, pas dans chaque écran."""

    def show(self, rgb):
        pass


def make(kind="ws2812", pin=None, pin_b=None):
    """Fabrique la LED décrite, ou un objet inerte si elle manque.

    Une LED mal câblée ne doit pas empêcher l'afficheur de démarrer : elle
    est un confort, pas une dépendance.
    """
    if pin is None:
        return NoLed()
    try:
        if kind == "bicolor":
            return Bicolor(pin, pin_b)
        return Rgb(pin)
    except Exception as e:
        print("led:", e)
        return NoLed()
