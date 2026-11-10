"""La dictée : une phrase dite au téléphone devient un évènement d'agenda.

« répondre à 18h au mail de conseil » devient « Répondre au mail de
conseil », aujourd'hui à 18 h, dans l'agenda Google « Awen » : sa
notification sonne à l'heure dite sur le téléphone, qui affiche cet agenda
comme les autres. La page /dictee s'installe sur l'écran d'accueil : une
touche, et le micro écoute.

L'ANALYSE EST FAITE DE RÈGLES, PAS D'UN MODÈLE

Une phrase dictée tient en quelques mots, et ses dates ont peu de formes :
« à 18h », « demain », « lundi », « le 15 novembre », « dans 2 heures »,
« ce soir ». Des règles répondent tout de suite, sans rien coûter, et
toujours de la même façon ; un modèle mettrait plusieurs secondes là où
l'on attend, le téléphone à la main. Ce que les règles comprennent mal se
corrige sur l'aperçu, avant d'ajouter.

SANS DATE NI HEURE, C'EST UNE TÂCHE

« acheter du pain » n'a pas de place dans un agenda : elle va dans les
tâches d'Awen, que l'écran du bureau et Jarvis montrent déjà. Et si Google
ne répond pas, la chose dictée n'est pas perdue : elle y va aussi, avec
son jour et son heure.
"""
import re
from datetime import date, datetime, time, timedelta

from flask import current_app

from ..models import Todo, db
from . import agenda_google, todos

JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre")
# Les mêmes, tels que la reconnaissance vocale peut les écrire.
MOIS_RE = ("janvier", "f[ée]vrier", "mars", "avril", "mai", "juin", "juillet",
           "ao[uû]t", "septembre", "octobre", "novembre", "d[ée]cembre")
NOMBRES = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5,
           "six": 6, "dix": 10, "quinze": 15, "vingt": 20, "trente": 30,
           "quarante": 40, "quarante-cinq": 45}
# L'heure que veut dire un moment de la journée dit sans heure.
MOMENTS = {"matin": time(9), "apres-midi": time(14), "soir": time(20)}

_I = re.I

# Ce qui introduit la chose à faire sans en faire partie.
PREFIXE = re.compile(
    r"^(?:(?:est-ce que tu peux |peux-tu |tu peux )?rappelle[sz]?[- ]moi"
    r"|n'oublie pas|il faut que je|il faut|je dois|penser? à|ajoute)\b"
    r"(?: (?:de |d'|que |qu'))?\s*", _I)
AGENDA = re.compile(r"\b(?:à|dans|sur) (?:mon |l'|le )?(?:agenda|calendrier)\b", _I)

N = r"(\d{1,3}|une?|deux|trois|quatre|cinq|six|dix|quinze|vingt|trente|quarante(?:-cinq)?)"
DANS = re.compile(r"\bdans " + N + r" ?(heures?|h|minutes?|mn|min)(?: ?(\d{2}))?\b", _I)
DANS_DEMI = re.compile(r"\bdans (?:une )?demi-heure\b", _I)
DANS_QUART = re.compile(r"\bdans un quart d'heure\b", _I)

AUJOURDHUI = re.compile(r"\baujourd'hui\b", _I)
APRES_DEMAIN = re.compile(r"\bapr[èe]s[- ]demain\b", _I)
DEMAIN = re.compile(r"\bdemain\b", _I)
JOUR_SEMAINE = re.compile(r"(?:\b(?:ce|le) )?\b(" + "|".join(JOURS) + r")(?: prochain)?\b", _I)
JOUR_MOIS = re.compile(r"(?:\ble )?\b(1er|premier|\d{1,2}) (" + "|".join(MOIS_RE)
                       + r")(?: (\d{4}))?\b", _I)
LE_N = re.compile(r"\ble (1er|premier|\d{1,2})\b(?! ?(?:h\b|heures?\b|:))", _I)

MOMENT = re.compile(r"(?:\b(?:ce|cet|cette|en|le|la|du|dans la|de la) |\b(?:dans|de) l')?"
                    r"\b(matin(?:ée)?|apr[èe]s[- ]midi|soir(?:ée)?)\b", _I)
MIDI = re.compile(r"(?:\b(?:à|vers|pour|dès) )?\bmidi(?: (et demie?|et quart))?\b", _I)
HEURE = re.compile(r"(?:\b(?:à|vers|pour|dès) )?\b(\d{1,2}) ?(?:h|heures?|:)(?: ?(\d{2}))?"
                   r"(?: (et demie?|et quart|moins le quart))?\b", _I)


def _nombre(mot):
    mot = mot.lower()
    return int(mot) if mot.isdigit() else NOMBRES.get(mot, 0)


def _minutes(h, m, suite):
    """L'heure, avec « et demie », « et quart », « moins le quart »."""
    suite = (suite or "").lower()
    if suite.startswith("et demi"):
        m += 30
    elif suite == "et quart":
        m += 15
    elif suite == "moins le quart":
        h, m = h - 1, m + 45
    return h, m


def _propre(texte):
    """Le titre : ce qui reste quand la date et l'heure sont parties."""
    t = re.sub(r"\s+", " ", texte).strip(" ,;:.-")
    t = re.sub(r"\s+([,.;:])", r"\1", t)
    for _ in range(3):
        t = re.sub(r"^(?:et|à|pour|puis)\b[ ,]*", "", t, flags=_I)
        t = re.sub(r"[ ,]*\b(?:et|à|pour|de|du|au|le|la|les)$", "", t, flags=_I)
        t = t.strip(" ,;:.-")
    return (t[:1].upper() + t[1:])[:todos.MAX_LEN] if t else ""


def analyser(phrase, maintenant=None):
    """La phrase dictée -> {phrase, titre, debut, jour}.

    `debut` : un datetime quand une heure est dite (ou « dans 2 heures »).
    `jour`  : une date quand seul le jour l'est : toute la journée.
    Les deux à None : pas de date, c'est une tâche.

    Une heure sans jour déjà passée aujourd'hui vaut pour demain : à 19 h,
    « à 18h » ne peut pas vouloir dire il y a une heure.
    """
    maintenant = (maintenant or datetime.now()).replace(second=0, microsecond=0)
    aujourdhui = maintenant.date()
    texte = " {} ".format(re.sub(r"\s+", " ", phrase or "").strip())
    phrase = texte.strip()

    def prendre(motif):
        nonlocal texte
        m = motif.search(texte)
        if m:
            texte = texte[:m.start()] + " " + texte[m.end():]
        return m

    texte = " " + PREFIXE.sub("", texte.strip()) + " "
    prendre(AGENDA)
    texte = " " + PREFIXE.sub("", texte.strip()) + " "

    # « dans 2 heures » : une heure exacte, rien d'autre à chercher.
    delta = None
    if prendre(DANS_DEMI):
        delta = timedelta(minutes=30)
    elif prendre(DANS_QUART):
        delta = timedelta(minutes=15)
    else:
        m = prendre(DANS)
        if m:
            n, unite = _nombre(m.group(1)), m.group(2).lower()
            if unite.startswith("h"):
                delta = timedelta(hours=n, minutes=int(m.group(3) or 0))
            else:
                delta = timedelta(minutes=n)
    if delta:
        return {"phrase": phrase, "titre": _propre(texte),
                "debut": maintenant + delta, "jour": None}

    jour = None
    if prendre(AUJOURDHUI):
        jour = aujourdhui
    elif prendre(APRES_DEMAIN):
        jour = aujourdhui + timedelta(days=2)
    elif prendre(DEMAIN):
        jour = aujourdhui + timedelta(days=1)
    else:
        m = prendre(JOUR_SEMAINE)
        if m:
            cible = JOURS.index(m.group(1).lower())
            jour = aujourdhui + timedelta(days=(cible - aujourdhui.weekday() - 1) % 7 + 1)
        else:
            m = JOUR_MOIS.search(texte)
            if m:
                n = 1 if m.group(1).lower() in ("1er", "premier") else int(m.group(1))
                mois = next(i for i, x in enumerate(MOIS_RE, 1)
                            if re.fullmatch(x, m.group(2), _I))
                annee = int(m.group(3)) if m.group(3) else aujourdhui.year
                try:
                    jour = date(annee, mois, n)
                    if not m.group(3) and jour < aujourdhui:
                        jour = date(annee + 1, mois, n)
                    prendre(JOUR_MOIS)
                except ValueError:
                    jour = None
            else:
                m = LE_N.search(texte)
                if m:
                    n = 1 if m.group(1).lower() in ("1er", "premier") else int(m.group(1))
                    try:
                        jour = aujourdhui.replace(day=n)
                        if jour < aujourdhui:
                            suivant = (aujourdhui.replace(day=1) + timedelta(days=32)).replace(day=1)
                            jour = suivant.replace(day=n)
                        prendre(LE_N)
                    except ValueError:
                        jour = None

    moment = None
    m = prendre(MOMENT)
    if m:
        mot = m.group(1).lower().replace("è", "e").replace(" ", "-")
        moment = "matin" if mot.startswith("matin") else (
            "soir" if mot.startswith("soir") else "apres-midi")

    heure = None
    m = prendre(MIDI)
    if m:
        h, mn = _minutes(12, 0, m.group(1))
        heure = time(h, mn)
    else:
        m = HEURE.search(texte)
        if m:
            h, mn = _minutes(int(m.group(1)), int(m.group(2) or 0), m.group(3))
            if moment in ("apres-midi", "soir") and h < 12:
                h += 12
            if 0 <= h <= 23 and 0 <= mn <= 59:
                heure = time(h, mn)
                prendre(HEURE)
    approchee = heure is None and moment is not None
    if approchee:
        heure = MOMENTS[moment]

    titre = _propre(texte)
    if heure is None:
        return {"phrase": phrase, "titre": titre, "debut": None, "jour": jour}
    debut = datetime.combine(jour or aujourdhui, heure)
    if debut <= maintenant:
        if not approchee and jour is None:
            debut += timedelta(days=1)
        elif approchee and debut.date() == aujourdhui:
            # « ce soir » dit à 21 h : c'est encore ce soir, au prochain quart d'heure.
            debut = maintenant + timedelta(minutes=15 - maintenant.minute % 15)
    return {"phrase": phrase, "titre": titre, "debut": debut, "jour": None}


def _le_jour(j, aujourdhui):
    if j == aujourdhui:
        return "aujourd'hui"
    if j == aujourdhui + timedelta(days=1):
        return "demain"
    return "{} {} {}".format(JOURS[j.weekday()], "1er" if j.day == 1 else j.day,
                             MOIS[j.month - 1])


def _h(d):
    return "{}h{:02d}".format(d.hour, d.minute) if d.minute else "{}h".format(d.hour)


def libelle(debut=None, jour=None, aujourdhui=None):
    """« aujourd'hui à 18h », « jeudi 12 novembre, toute la journée »."""
    aujourdhui = aujourdhui or date.today()
    if debut is not None:
        return "{} à {}".format(_le_jour(debut.date(), aujourdhui), _h(debut))
    if jour is not None:
        return "{}, toute la journée".format(_le_jour(jour, aujourdhui))
    return "sans date"


def ajouter(titre, debut=None, jour=None):
    """Range la chose dictée : l'agenda si elle a un jour, les tâches sinon.

    Renvoie {type, id, message} ; `type` vaut « evenement » ou « tache ».
    """
    titre = (titre or "").strip()[:todos.MAX_LEN] or "Rappel"
    quand = libelle(debut, jour)
    repli = ""
    if debut is not None or jour is not None:
        if agenda_google.actif():
            try:
                eid = agenda_google.poser(titre, debut=debut, jour=jour,
                                          description="Dicté dans Awen.")
                return {"type": "evenement", "id": eid,
                        "message": "Dans l'agenda Awen, {}.".format(quand)}
            except Exception as exc:                 # réseau, clé, droits...
                current_app.logger.warning("dictée, agenda Google : %s", exc)
                repli = "Google Agenda n'a pas répondu : "
        else:
            repli = "L'agenda Google n'est pas configuré : "
    texte = titre if debut is None else "{} ({})".format(titre, _h(debut))
    t = todos.add(texte, due=debut.date() if debut else jour, source="dictee")
    message = ("{}notée dans tes tâches, {}.".format(repli, quand) if repli
               else "Sans date : dans tes tâches d'Awen.")
    return {"type": "tache", "id": t.id, "message": message}


def annuler(genre, ident):
    """Le bouton Annuler, juste après l'ajout."""
    if genre == "evenement":
        agenda_google.enlever(str(ident))
    elif genre == "tache":
        t = db.session.get(Todo, int(ident))
        if t is not None and t.source == "dictee":
            db.session.delete(t)
            db.session.commit()
