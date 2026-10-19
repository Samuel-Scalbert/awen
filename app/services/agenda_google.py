"""Le rappel de séance, écrit par le serveur dans un agenda Google « Awen ».

Le téléphone n'a rien à aller chercher : Awen écrit lui-même l'évènement
dans un agenda Google que le téléphone synchronise déjà comme les autres.
Ni Tailscale ni application d'abonnement ne sont nécessaires.

- Une séance commence : un évènement « Awen : termine ta séance Push » est
  posé le soir même (voir rappels.moment).
- Elle est terminée, annulée ou remplacée : l'évènement est retiré.

S'il est encore dans l'agenda le soir, c'est que la séance n'est pas finie,
et sa notification sonne.

L'accès passe par un compte de service Google, un robot avec lequel l'agenda
« Awen » est partagé : aucune connexion à renouveler, et le robot ne voit que
cet agenda-là. La notification est celle que l'agenda « Awen » applique par
défaut à ses évènements, réglée une fois dans Google Agenda : un rappel posé
par le robot ne vaudrait que pour le robot.

Sans GOOGLE_CALENDAR_ID ou sans la clé du robot, rien ne se passe. Chaque
appel tourne en arrière-plan : à la salle, un Google lent ou injoignable ne
doit jamais retarder le choix d'une séance.
"""
import threading
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

from flask import current_app

from . import rappels

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
API = "https://www.googleapis.com/calendar/v3/calendars/{}/events"
FUSEAU = "Europe/Paris"
DUREE = timedelta(minutes=15)


def actif():
    cfg = current_app.config
    cle = cfg.get("GOOGLE_SERVICE_ACCOUNT_FILE") or ""
    return bool(cfg.get("GOOGLE_CALENDAR_ID")) and Path(cle).is_file()


def identifiant(workout_id, commencee):
    """L'identifiant de l'évènement d'une séance, retrouvable sans rien
    stocker. Google n'accepte que les lettres a à v et les chiffres ; la date
    de début évite de retomber sur l'évènement d'une séance supprimée dont la
    base aurait réutilisé le numéro."""
    return "seance{}{:%Y%m%d%H%M%S}".format(workout_id, commencee)


def _session():
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_file(
        current_app.config["GOOGLE_SERVICE_ACCOUNT_FILE"], scopes=SCOPES)
    return AuthorizedSession(creds)


def _url(*suite):
    base = API.format(quote(current_app.config["GOOGLE_CALENDAR_ID"], safe=""))
    return "/".join((base,) + suite)


def _heure(dt):
    return {"dateTime": dt.isoformat(timespec="seconds"), "timeZone": FUSEAU}


def _creer(workout_id, focus, commencee, lien):
    quand = rappels.moment(commencee)
    corps = {
        "id": identifiant(workout_id, commencee),
        "summary": rappels.titre(focus),
        "description": ("Commencée à {}. Si elle est finie, touche « Terminer "
                        "la séance » dans Awen : c'est ce qui applique la "
                        "progression.\n{}").format(commencee.strftime("%Hh%M"), lien),
        "start": _heure(quand),
        "end": _heure(quand + DUREE),
        "reminders": {"useDefault": True},
        # N'occupe pas la soirée : les invitations ne la voient pas prise.
        "transparency": "transparent",
    }
    s = _session()
    r = s.post(_url(), json=corps, timeout=15)
    if r.status_code == 409:
        # L'identifiant existe déjà (évènement supprimé puis recréé) : on le
        # remet à jour et on le rétablit.
        corps["status"] = "confirmed"
        r = s.put(_url(corps["id"]), json=corps, timeout=15)
    r.raise_for_status()


def _supprimer(workout_id, commencee):
    r = _session().delete(_url(identifiant(workout_id, commencee)), timeout=15)
    if r.status_code not in (200, 204, 404, 410):     # déjà parti : très bien
        r.raise_for_status()


def _en_fond(fonction, *args):
    app = current_app._get_current_object()

    def tache():
        with app.app_context():
            try:
                fonction(*args)
            except Exception as exc:                 # réseau, clé, droits…
                app.logger.warning("agenda Google : %s", exc)

    threading.Thread(target=tache, daemon=True).start()


def planifier(workout, lien):
    """Pose le rappel d'une séance qui commence."""
    if actif():
        _en_fond(_creer, workout.id, workout.focus, workout.date, lien)


def retirer(workout):
    """Retire le rappel d'une séance terminée, annulée ou remplacée.

    À appeler avant de supprimer la séance : on lit son numéro et sa date
    tant qu'elle existe encore.
    """
    if actif():
        _en_fond(_supprimer, workout.id, workout.date)
