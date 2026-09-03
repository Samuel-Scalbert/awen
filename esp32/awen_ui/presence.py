"""Détection de présence par sonar, pour éteindre l'écran quand tu pars.

Le HC-SR04 mesure un temps d'écho, dont on tire une distance. Sous un seuil,
quelqu'un est là ; au-dessus, la pièce est vide et le panneau n'éclaire
personne.

DEUX LECTURES D'ACCORD, JAMAIS UNE SEULE

Un sonar renvoie des aberrations : un écho sur le bord du bureau, une salve
perdue dans un angle, une réflexion parasite. Prendre une mesure isolée pour
argent comptant aurait deux conséquences symétriques et toutes deux
pénibles — un faux « présent » relancerait le compte à rebours en boucle et
l'écran ne s'éteindrait jamais, un faux « absent » ne coûte rien puisque
c'est un délai de dix minutes qui décide, mais un faux réveil en pleine nuit
allumerait la pièce.

On exige donc deux lectures consécutives d'accord avant de changer d'avis.
C'est le filtre le plus simple qui traite les deux cas.

LE SEUIL SE MESURE, IL NE SE DEVINE PAS

Il dépend d'où le capteur est posé et de la profondeur du bureau. Celui de
Samuel : assis, 70 à 75 cm ; bureau vide, 235 cm. Le seuil est à 120 cm,
bien au-dessus de la position la plus reculée et bien en dessous du mur.
`selftest.py` refait la mesure et propose la valeur.
"""
import time

from machine import Pin, time_pulse_us

# Un aller-retour parcourt 2 cm par 58 µs : le son fait 343 m/s, soit
# 29,1 µs par centimètre, doublé par le trajet retour.
US_PER_CM = 58
# Une salve sans obstacle dure jusqu'à 38 ms. En dessous, on couperait une
# mesure valide et on la lirait comme une absence.
TIMEOUT_US = 40000


class Sonar:
    """Un HC-SR04, réduit à une question : « quelqu'un est là ? »."""

    def __init__(self, trig, echo, threshold_cm=120, every_ms=500,
                 idle_ms=600000):
        self.trig = Pin(trig, Pin.OUT)
        self.echo = Pin(echo, Pin.IN)
        self.threshold = threshold_cm
        self.every = every_ms
        self.idle = idle_ms

        self.present = True         # au démarrage on suppose quelqu'un : un
                                    # afficheur qui s'allume noir inquiète
        self.distance = 0
        self._candidate = None      # ce que dit la dernière lecture
        self._t_read = 0
        self._t_seen = time.ticks_ms()

    def measure(self):
        """Distance en cm, ou 0 si la mesure a échoué."""
        self.trig.value(0)
        time.sleep_us(5)
        self.trig.value(1)
        time.sleep_us(10)           # la salve se déclenche sur 10 µs
        self.trig.value(0)
        try:
            us = time_pulse_us(self.echo, 1, TIMEOUT_US)
        except OSError:
            return 0
        return us // US_PER_CM if us > 0 else 0

    def poll(self, now):
        """À appeler à chaque image. Renvoie True QUAND QUELQU'UN REVIENT.

        Seul le retour est un événement : c'est lui qui doit rallumer tout de
        suite. Le départ, lui, ne décide de rien — c'est le délai de
        `expired()` qui tranche, pas la première seconde de vide.

        Une mesure prend jusqu'à 40 ms, pendant lesquelles la boucle ne lit
        pas les boutons : d'où l'espacement à 500 ms, largement suffisant
        pour une décision qui se compte en minutes.
        """
        if time.ticks_diff(now, self._t_read) < self.every:
            return False
        self._t_read = now

        cm = self.measure()
        self.distance = cm
        # UNE MESURE RATEE EST IGNOREE, PAS INTERPRETEE.
        #
        # Le capteur manque des echos : vetement sombre, surface oblique,
        # salve perdue. C'est le cas normal, pas l'exception.
        #
        # Elle remettait `_candidate` a None, ce qui cassait la chaine de
        # confirmation. Un mur qui ne repond qu'une fois sur deux suffisait
        # alors a ce que plus rien ne soit jamais confirme : `present`
        # restait bloque sur sa derniere valeur, l'ecran s'endormait par
        # expiration du delai, et le retour ne produisait aucun front.
        # L'ecran ne se rallumait plus jamais.
        if cm <= 0:
            return False

        vu = cm < self.threshold
        confirme = (self._candidate == vu)
        self._candidate = vu
        if not confirme:
            return False            # une lecture isolée ne décide de rien

        if vu:
            # Le chronomètre repart tant qu'on est vu, écran déjà allumé ou
            # non : c'est lui qui porte les dix minutes.
            self._t_seen = now
        if vu == self.present:
            return False
        self.present = vu
        return vu

    def forget(self):
        """Oublie la presence, quand l'afficheur s'endort.

        Sans cet oubli, l'app qui se reveille sur l'ETAT `present` — et
        non plus sur un front — se rendormirait aussitot puis se
        rallumerait en boucle : elle verrait une presence que le delai
        vient justement de declarer perimee.
        """
        self.present = False
        self._candidate = None

    def seen(self, now):
        """Déclare une présence sans passer par le capteur.

        Un appui sur un bouton prouve mieux qu'un écho que quelqu'un est là.
        Sans cette entrée, le réveil au doigt serait rendormi à l'image
        suivante par un chronomètre resté vieux de dix minutes.
        """
        self._t_seen = now
        self.present = True
        self._candidate = True

    def expired(self, now):
        """Vrai quand personne n'a été vu depuis assez longtemps."""
        return time.ticks_diff(now, self._t_seen) >= self.idle

    def idle_ms(self, now):
        return time.ticks_diff(now, self._t_seen)


class NoSonar:
    """Sans capteur, il y a toujours quelqu'un : l'écran reste allumé."""

    present = True
    distance = 0

    def poll(self, now):
        return False

    def forget(self):
        pass

    def seen(self, now):
        pass

    def expired(self, now):
        return False

    def idle_ms(self, now):
        return 0


def make(trig=None, echo=None, **kw):
    if trig is None or echo is None:
        return NoSonar()
    try:
        return Sonar(trig, echo, **kw)
    except Exception:
        return NoSonar()
