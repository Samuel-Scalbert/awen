"""Jarvis : le modèle local, et les outils par lesquels il voit Awen.

CE QUI FAIT LA DIFFÉRENCE AVEC UN ROBOT CONVERSATIONNEL

Un modèle de 8B qui répond de tête n'a aucun intérêt : il y en a de bien
meilleurs dans le navigateur. Tout l'intérêt est ici, dans la liste `TOOLS` —
des fonctions qui interrogent la vraie base. Le modèle ne sert qu'à choisir
laquelle appeler et à mettre le résultat en français.

LA RÈGLE QUI ÉVITE LES CHIFFRES INVENTÉS

Aucun nombre ne sort du modèle. Les chiffres viennent des outils, et la
consigne système le lui dit : s'il n'a pas appelé d'outil, il n'a pas le droit
d'affirmer un chiffre. C'est la seule défense qui tienne face à un modèle de
cette taille, qui produit volontiers un « tu as fait 14 séances en août » très
convaincant et parfaitement faux.

POURQUOI PAS DE BASE VECTORIELLE

Les données d'Awen sont petites, structurées et déjà interrogeables. « Combien
de séances ratées en août » a une réponse exacte : c'est un COUNT, pas une
recherche par similarité. Un index à tenir à jour coûterait de l'entretien pour
des réponses approximatives.

DEUX SORTIES À CHAQUE TOUR

`reponse` pour le navigateur, `ecran` pour l'ESP32 — 60 caractères, demandés au
modèle plutôt que tronqués après coup : une phrase coupée au milieu est
illisible, une phrase courte ne l'est pas.
"""
import json
from datetime import date, datetime, timedelta

import requests
from flask import current_app

from ..models import ProgramExercise, Workout
from . import attendance, calendar_sync, coach, host, job_watch, stats, todos
from .progression import plan_upcoming

TIMEOUT_S = 120        # un 8B sur une 3070 répond en quelques secondes ;
                       # la marge couvre le premier chargement du modèle.
MAX_TOURS = 4          # au-delà, le modèle tourne en rond plutôt qu'il ne
                       # cherche : mieux vaut répondre avec ce qu'on a.
ECRAN_MAX = 60

SYSTEME = """Tu es Jarvis, le majordome de Samuel. Tu vis sur son serveur et
tu as accès à ses données personnelles par des outils.

Règles absolues :
- N'invente JAMAIS un chiffre, une date ou un nom. Si tu n'as pas appelé
  d'outil, tu n'as pas le droit d'affirmer un fait chiffré : appelle l'outil,
  ou dis que tu ne sais pas.
- Réponds en français, brièvement. Deux ou trois phrases suffisent presque
  toujours. Pas de liste à puces sauf si on te demande une liste.
- Ton de majordome : courtois, direct, un peu sec. Jamais servile, jamais
  bavard.
- Tu peux ajouter et terminer des tâches. Tu ne peux rien modifier d'autre.

Termine TOUJOURS ta réponse par une dernière ligne de cette forme exacte :
ECRAN: <résumé de 60 caractères maximum, sans accent>
Cette ligne est affichée sur un petit écran de 30 colonnes."""


# ---------------------------------------------------------------- les outils

def _seance_du_jour():
    """Le focus prevu aujourd'hui, ou le prochain si c'est un jour de repos.

    `plan_upcoming` projette STRICTEMENT apres la date donnee : partir
    d'aujourd'hui sauterait la seance du jour. On part donc de la veille, ou
    de la derniere seance faite si elle est plus recente — la meme regle que
    dans routes/esp32.py, et pour la meme raison.
    """
    today = date.today()
    last = (Workout.query.filter_by(completed=True)
            .order_by(Workout.date.desc()).first())
    last_focus = last.focus if last else None
    last_date = last.date.date() if last else None
    after = max(d for d in (last_date, today - timedelta(days=1)) if d)
    plan = plan_upcoming(last_focus, after, count=8)
    aujourdhui = next((f for d, f in plan if d == today), None)
    prochain_jour, prochain_focus = plan[0] if plan else (None, None)
    focus = aujourdhui or prochain_focus
    exos = [{"nom": pe.name, "charge_kg": pe.weight_kg,
             "reps": "{}-{}".format(pe.rep_min, pe.rep_max)}
            for pe in ProgramExercise.query
            .filter(ProgramExercise.active.is_(True),
                    ProgramExercise.session_type == (focus or "").lower())
            .order_by(ProgramExercise.position)]
    return {"aujourd_hui": bool(aujourdhui),
            "focus": focus,
            "prochaine_date": (today if aujourdhui else prochain_jour).isoformat()
                              if (aujourdhui or prochain_jour) else None,
            "exercices": exos}


def _assiduite():
    s = attendance.summary()
    return {"seances_ratees": s["rate"], "absences": s["absent"],
            "a_qualifier": s["todo"], "serie_en_cours": s["streak"],
            "pire_serie": s["longest"]}


def _conseil_du_coach():
    return [{"niveau": a["level"], "texte": a.get("text") or a.get("title", "")}
            for a in coach.analyse()[:6]]


def _progression():
    o = stats.overview()
    return {"seances_totales": len(o.get("sessions", [])),
            "volume_total_kg": o.get("total_volume"),
            "series_totales": o.get("total_sets"),
            "reps_totales": o.get("total_reps")}


def _prochains_evenements(n=5):
    try:
        evts = calendar_sync.get_upcoming_events(limit=int(n))
    except Exception as exc:                       # réseau, ICS illisible…
        return {"erreur": str(exc)[:120]}
    return [{"titre": e.get("summary"), "debut": str(e.get("start"))}
            for e in evts]


def _veille_emploi():
    reports = job_watch.get_daily_reports(limit=1)
    if not reports:
        return {"info": "aucun compte rendu de veille disponible"}
    r = reports[0]
    return {"date": r.get("date_fr"),
            "offres": [o.get("title") for o in r.get("offers", [])]}


def _etat_serveur():
    return host.summary()


def _taches_en_cours():
    return [{"id": t.id, "texte": t.text,
             "echeance": t.due.isoformat() if t.due else None}
            for t in todos.pending(20)]


def _ajouter_tache(texte, echeance=None):
    due = None
    if echeance:
        try:
            due = date.fromisoformat(echeance)
        except ValueError:
            due = None
    entry = todos.add(texte, due, source="jarvis")
    if entry is None:
        return {"erreur": "texte vide, rien enregistré"}
    return {"ajoutee": entry.text, "id": entry.id}


def _terminer_tache(texte):
    entry = todos.complete_by_text(texte)
    if entry is None:
        return {"erreur": "aucune tâche en cours ne correspond"}
    return {"terminee": entry.text}


# Le schéma est celui qu'attend l'API d'Ollama, calquée sur celle d'OpenAI.
# La description compte autant que le code : c'est tout ce que le modèle lit
# pour décider s'il appelle cet outil.
TOOLS = [
    {"fn": _seance_du_jour, "nom": "seance_du_jour",
     "desc": "La séance d'entraînement prévue aujourd'hui : son type "
             "(Push/Pull/Legs) et la liste des exercices avec charges et "
             "répétitions.", "args": {}},
    {"fn": _assiduite, "nom": "assiduite",
     "desc": "Combien de séances ont été ratées, combien d'absences "
             "excusées, et la série de séances ratées en cours.", "args": {}},
    {"fn": _conseil_du_coach, "nom": "conseil_du_coach",
     "desc": "Les observations du coach : stagnations, douleurs signalées, "
             "charges à augmenter, deload conseillé.", "args": {}},
    {"fn": _progression, "nom": "progression",
     "desc": "Les totaux d'entraînement : nombre de séances, volume soulevé, "
             "séries et répétitions.", "args": {}},
    {"fn": _prochains_evenements, "nom": "prochains_evenements",
     "desc": "Les prochains rendez-vous du calendrier.",
     "args": {"n": {"type": "integer",
                    "description": "Combien d'événements, 5 par défaut."}}},
    {"fn": _veille_emploi, "nom": "veille_emploi",
     "desc": "Le dernier compte rendu de veille emploi et les offres "
             "retenues.", "args": {}},
    {"fn": _etat_serveur, "nom": "etat_serveur",
     "desc": "L'état du serveur : conteneurs en marche, mémoire, disque, "
             "durée de fonctionnement.", "args": {}},
    {"fn": _taches_en_cours, "nom": "taches_en_cours",
     "desc": "La liste des tâches à faire, les plus urgentes d'abord.",
     "args": {}},
    {"fn": _ajouter_tache, "nom": "ajouter_tache",
     "desc": "Ajoute une tâche à la liste.",
     "args": {"texte": {"type": "string", "description": "La tâche."},
              "echeance": {"type": "string",
                           "description": "Date AAAA-MM-JJ, facultative."}},
     "requis": ["texte"]},
    {"fn": _terminer_tache, "nom": "terminer_tache",
     "desc": "Marque comme terminée la tâche dont le texte contient ce "
             "fragment.",
     "args": {"texte": {"type": "string",
                        "description": "Un fragment du texte de la tâche."}},
     "requis": ["texte"]},
]

_PAR_NOM = {t["nom"]: t for t in TOOLS}


def _schema():
    return [{"type": "function",
             "function": {"name": t["nom"], "description": t["desc"],
                          "parameters": {"type": "object",
                                         "properties": t["args"],
                                         "required": t.get("requis", [])}}}
            for t in TOOLS]


def _appeler(nom, args):
    """Exécute un outil. Une erreur devient une donnée, pas une exception.

    Renvoyer l'erreur au modèle lui permet de dire « je n'ai pas pu vérifier »
    au lieu de s'arrêter net — et c'est infiniment préférable à une page 500
    quand une synchronisation de calendrier échoue.
    """
    outil = _PAR_NOM.get(nom)
    if outil is None:
        return {"erreur": "outil inconnu : {}".format(nom)}
    try:
        return outil["fn"](**(args or {}))
    except TypeError as exc:
        return {"erreur": "arguments invalides : {}".format(exc)}
    except Exception as exc:                       # pragma: no cover
        return {"erreur": "{}: {}".format(type(exc).__name__, exc)}


# ------------------------------------------------------------------- Ollama

def _url(chemin):
    base = current_app.config["OLLAMA_URL"].rstrip("/")
    return "{}{}".format(base, chemin)


def health():
    """Ollama répond-il, et le modèle configuré est-il présent ?

    Trois états distincts, parce qu'ils appellent trois gestes différents :
    serveur absent (installer/démarrer), modèle absent (ollama pull), prêt.
    """
    try:
        r = requests.get(_url("/api/tags"), timeout=3)
        r.raise_for_status()
        noms = [m.get("name", "") for m in r.json().get("models", [])]
    except requests.RequestException as exc:
        return {"ok": False, "etat": "absent",
                "detail": type(exc).__name__, "modeles": []}

    voulu = current_app.config["OLLAMA_MODEL"]
    # Ollama nomme « qwen3:8b » ; une configuration sans tag doit matcher.
    present = any(n == voulu or n.split(":")[0] == voulu.split(":")[0]
                  for n in noms)
    return {"ok": present, "etat": "pret" if present else "modele-absent",
            "modele": voulu, "modeles": noms}


def _chat(messages):
    corps = {"model": current_app.config["OLLAMA_MODEL"],
             "messages": messages,
             "tools": _schema(),
             "stream": False,
             # Qwen3 reflechit a voix haute par defaut : « Okay, the user
             # asked... » sur 1500 jetons pour dire bonjour. C'est du temps
             # d'attente et du texte a masquer, pour une question de
             # majordome qui n'en a aucun besoin. Les modeles sans mode
             # reflexion ignorent simplement ce champ.
             "think": False,
             "keep_alive": current_app.config["OLLAMA_KEEP_ALIVE"],
             "options": {"temperature": 0.3}}
    r = requests.post(_url("/api/chat"), json=corps, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json().get("message", {})


def _decouper(texte):
    """Sépare la réponse longue de la ligne ECRAN: demandée au modèle."""
    reponse, ecran = texte.strip(), ""
    for ligne in texte.strip().splitlines()[::-1]:
        if ligne.strip().upper().startswith("ECRAN:"):
            ecran = ligne.split(":", 1)[1].strip()[:ECRAN_MAX]
            reponse = texte.replace(ligne, "").strip()
            break
    if not ecran:
        # Le modèle a oublié la consigne : on prend la première phrase plutôt
        # que de laisser l'afficheur vide.
        ecran = reponse.split(".")[0][:ECRAN_MAX]
    return reponse, ecran


def ask(question, historique=None):
    """Une question, une réponse. Jamais d'exception vers la route.

    `outils` liste ce qui a réellement été consulté : c'est ce qui permet de
    voir, dans le HUD, qu'une réponse s'appuie sur la base et pas sur
    l'imagination du modèle.
    """
    question = (question or "").strip()
    if not question:
        return {"ok": False, "reponse": "Vous n'avez rien demandé.",
                "ecran": "", "outils": []}

    messages = [{"role": "system", "content": SYSTEME}]
    messages += (historique or [])[-6:]
    messages.append({"role": "user", "content": question})

    utilises = []
    try:
        for _ in range(MAX_TOURS):
            msg = _chat(messages)
            appels = msg.get("tool_calls") or []
            if not appels:
                reponse, ecran = _decouper(msg.get("content", ""))
                return {"ok": True, "reponse": reponse, "ecran": ecran,
                        "outils": utilises}

            messages.append(msg)
            for appel in appels:
                f = appel.get("function", {})
                nom = f.get("name", "")
                args = f.get("arguments") or {}
                if isinstance(args, str):          # certains modèles le
                    try:                           # sérialisent en JSON
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                resultat = _appeler(nom, args)
                utilises.append(nom)
                messages.append({"role": "tool", "name": nom,
                                 "content": json.dumps(resultat,
                                                       ensure_ascii=False,
                                                       default=str)})
        return {"ok": True, "outils": utilises,
                "reponse": "Je tourne en rond sur cette question — "
                           "reformulez-la, je vous prie.",
                "ecran": "Question trop complexe"}

    except requests.RequestException as exc:
        etat = health()
        if etat["etat"] == "absent":
            texte = ("Le modèle n'est pas joignable. Ollama tourne-t-il sur "
                     "le serveur ?")
        elif etat["etat"] == "modele-absent":
            texte = ("Le modèle {} n'est pas installé. Lancez « ollama pull "
                     "{} » sur le serveur.".format(etat["modele"],
                                                   etat["modele"]))
        else:
            detail = getattr(getattr(exc, "response", None), "text", "") or ""
            texte = "Le modèle a refusé la requête ({}) : {}".format(
                type(exc).__name__, detail[:200] or "pas de détail")
        return {"ok": False, "reponse": texte, "ecran": "Modele injoignable",
                "outils": utilises}


def sans_modele(question):
    """Ce que Jarvis sait répondre quand Ollama n'est pas encore là.

    Le HUD doit être utilisable avant l'installation du pilote NVIDIA : sans
    ce repli, toute la page attendrait une étape qui demande un redémarrage
    du serveur. Les outils, eux, fonctionnent déjà.
    """
    q = (question or "").lower()
    table = [(("séance", "seance", "entrain", "muscu", "salle"),
              "seance_du_jour"),
             (("tâche", "tache", "todo", "liste"), "taches_en_cours"),
             (("coach", "conseil", "charge"), "conseil_du_coach"),
             (("rendez", "agenda", "calendrier", "événement", "evenement"),
              "prochains_evenements"),
             (("emploi", "offre", "job", "veille"), "veille_emploi"),
             (("serveur", "machine", "conteneur"), "etat_serveur"),
             (("assiduité", "assiduite", "raté", "rate", "absence"),
              "assiduite")]
    for mots, nom in table:
        if any(m in q for m in mots):
            return {"ok": True, "outil": nom, "donnees": _appeler(nom, {}),
                    "ecran": nom.replace("_", " ")[:ECRAN_MAX]}
    return {"ok": False, "outil": None, "donnees": None,
            "ecran": "Modele absent"}


def etat_complet():
    """Tout ce que le HUD affiche dans sa barre haute, en un appel."""
    return {"ollama": health(), "hote": host.summary(),
            "taches": todos.counts(),
            "heure": datetime.now().strftime("%H:%M:%S"),
            "date": date.today().strftime("%d/%m/%Y")}
