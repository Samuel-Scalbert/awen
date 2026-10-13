"""L'agenda envoyé à l'afficheur, vérifié sur un flux ICS écrit à la main.

    python -m unittest tests.test_agenda

Le flux réunit les cas qui font mentir un agenda : heure en UTC, heure
flottante, journée entière sur deux jours, série hebdomadaire avec une date
retirée et une occurrence déplacée, évènement annulé. Rien ne sort sur le
réseau : le téléchargement, la météo et Spotify sont remplacés.
"""
import unittest
from datetime import date, datetime, timezone
from unittest import mock

from app import create_app
from app.config import Config
from app.routes import esp32
from app.services import calendar_sync

ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//awen//test//FR
BEGIN:VEVENT
UID:fuseau
DTSTART;TZID=Europe/Paris:20261013T110000
DTEND;TZID=Europe/Paris:20261013T120000
SUMMARY:Entretien visio
END:VEVENT
BEGIN:VEVENT
UID:utc
DTSTART:20261013T070000Z
DTEND:20261013T073000Z
SUMMARY:Revue des offres
END:VEVENT
BEGIN:VEVENT
UID:flottant
DTSTART:20261013T143000
SUMMARY:Dentiste
END:VEVENT
BEGIN:VEVENT
UID:serie-mardi
DTSTART;TZID=Europe/Paris:20260901T183000
DTEND;TZID=Europe/Paris:20260901T200000
RRULE:FREQ=WEEKLY;BYDAY=TU;UNTIL=20261231T225959Z
EXDATE;TZID=Europe/Paris:20261020T183000
SUMMARY:Séance : Pull \U0001f4aa
END:VEVENT
BEGIN:VEVENT
UID:serie-mercredi
DTSTART;TZID=Europe/Paris:20261007T100000
DTEND;TZID=Europe/Paris:20261007T110000
RRULE:FREQ=WEEKLY;BYDAY=WE
SUMMARY:Atelier Data
END:VEVENT
BEGIN:VEVENT
UID:serie-mercredi
RECURRENCE-ID;TZID=Europe/Paris:20261014T100000
DTSTART;TZID=Europe/Paris:20261014T160000
DTEND;TZID=Europe/Paris:20261014T170000
SUMMARY:Atelier Data (décalé)
END:VEVENT
BEGIN:VEVENT
UID:deux-jours
DTSTART;VALUE=DATE:20261015
DTEND;VALUE=DATE:20261017
SUMMARY:Salon de l’emploi
END:VEVENT
BEGIN:VEVENT
UID:annule
DTSTART;TZID=Europe/Paris:20261013T160000
STATUS:CANCELLED
SUMMARY:Annulé
END:VEVENT
BEGIN:VEVENT
UID:annuel
DTSTART;VALUE=DATE:20201013
RRULE:FREQ=YEARLY;UNTIL=20301013
SUMMARY:Anniversaire Léa
END:VEVENT
END:VCALENDAR
""".replace("\n", "\r\n").encode("utf-8")


class ConfigTest(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"      # en mémoire : rien sur le disque
    SAMSUNG_CALENDAR_ICS_URL = "https://exemple.invalid/agenda.ics"
    ESP32_API_KEY = "cle-de-test"


class Reponse:
    content = ICS
    headers = {"Content-Type": "text/calendar"}

    def raise_for_status(self):
        pass


def _heure_locale(aaaa, mm, jj, h, m):
    """Ce que vaut un instant UTC sur l'horloge de la machine de test."""
    return (datetime(aaaa, mm, jj, h, m, tzinfo=timezone.utc)
            .astimezone().replace(tzinfo=None))


class AgendaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(ConfigTest)

    def setUp(self):
        calendar_sync._cache.update(at=0.0, url=None, cal=None)
        self.ctx = self.app.app_context()
        self.ctx.push()
        patch = mock.patch.object(calendar_sync.requests, "get",
                                  return_value=Reponse())
        self.get = patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.ctx.pop)

    def _jour(self, d):
        events, status = calendar_sync.occurrences(d, d)
        self.assertEqual(status, "ok")
        return [(e["start"].strftime("%H:%M"), e["title"], e["all_day"])
                for e in events]

    def test_un_mardi_charge(self):
        utc = _heure_locale(2026, 10, 13, 7, 0).strftime("%H:%M")
        attendu = sorted([
            ("00:00", "Anniversaire Léa", True),
            (utc, "Revue des offres", False),
            ("11:00", "Entretien visio", False),
            ("14:30", "Dentiste", False),
            ("18:30", "Séance : Pull \U0001f4aa", False),
        ])
        self.assertEqual(sorted(self._jour(date(2026, 10, 13))), attendu)

    def test_occurrence_deplacee_ne_compte_qu_une_fois(self):
        self.assertEqual(self._jour(date(2026, 10, 14)),
                         [("16:00", "Atelier Data (décalé)", False)])
        # La semaine suivante, la série reprend son heure.
        self.assertEqual(self._jour(date(2026, 10, 21)),
                         [("10:00", "Atelier Data", False)])

    def test_date_retiree_de_la_serie(self):
        self.assertEqual(self._jour(date(2026, 10, 20)), [])
        # Après le passage à l'heure d'hiver du 25, la séance reste à 18:30.
        self.assertEqual(self._jour(date(2026, 10, 27)),
                         [("18:30", "Séance : Pull \U0001f4aa", False)])

    def test_journees_entieres_sur_deux_jours(self):
        for jour in (15, 16):
            self.assertEqual(self._jour(date(2026, 10, jour)),
                             [("00:00", "Salon de l’emploi", True)])
        self.assertEqual(self._jour(date(2026, 10, 17)), [])

    def test_le_flux_n_est_telecharge_qu_une_fois(self):
        calendar_sync.occurrences(date(2026, 10, 13), date(2026, 10, 13))
        calendar_sync.occurrences(date(2026, 10, 14), date(2026, 10, 14))
        self.assertEqual(self.get.call_count, 1)

    def test_bloc_agenda_a_9h41(self):
        maintenant = datetime(2026, 10, 13, 9, 41)
        bloc = esp32._agenda_block(maintenant)
        self.assertTrue(bloc["ok"])
        self.assertEqual(bloc["n"], 5)
        self.assertEqual(bloc["dans"], "DANS 1 H 19")
        # Quatre lignes cadrées sur ce qui arrive : l'anniversaire sort du
        # cadre, le rendez-vous passé reste pour situer le suivant.
        self.assertEqual([l[1] for l in bloc["jour"]],
                         ["Revue des offres", "Entretien visio", "Dentiste",
                          "Séance : Pull"])
        self.assertEqual([l[2] for l in bloc["jour"]], [0, 1, 2, 2])
        self.assertEqual(bloc["jour"][1][0], "11:00")

        titres = [(j["t"], j["d"], [l[1] for l in j["ev"]])
                  for j in bloc["jours"][:4]]
        self.assertEqual(titres, [
            ("AUJOURD'HUI", "MAR 13", ["Anniversaire Léa", "Entretien visio",
                                       "Dentiste", "Séance : Pull"]),
            ("DEMAIN", "MER 14", ["Atelier Data (décalé)"]),
            ("JEUDI", "JEU 15", ["Salon de l'emploi"]),
            ("VENDREDI", "VEN 16", ["Salon de l'emploi"]),
        ])
        self.assertEqual(bloc["semaine"], [
            ["L", 12, 0], ["M", 13, 1], ["M", 14, 1], ["J", 15, 1],
            ["V", 16, 1], ["S", 17, 0], ["D", 18, 0]])
        self.assertEqual((bloc["auj"], bloc["mois"], bloc["annee"]),
                         (1, "Octobre", 2026))

    def test_bloc_agenda_pendant_un_rendez_vous(self):
        bloc = esp32._agenda_block(datetime(2026, 10, 13, 11, 20))
        self.assertEqual(bloc["dans"], "EN COURS")
        self.assertEqual([l[2] for l in bloc["jour"]], [0, 1, 2, 2])

    def test_bloc_agenda_le_soir(self):
        bloc = esp32._agenda_block(datetime(2026, 10, 13, 22, 0))
        self.assertEqual(bloc["dans"], "")
        self.assertEqual(len(bloc["jour"]), 4)
        self.assertEqual(bloc["jours"][0]["t"], "AUJOURD'HUI")
        self.assertEqual([l[1] for l in bloc["jours"][0]["ev"]],
                         ["Anniversaire Léa"])

    def test_route_pages(self):
        meteo = {"now_c": 18, "min_c": 12, "max_c": 19, "rain_pct": 15,
                 "label": "PLUIE FAIBLE", "icon": "'"}
        with mock.patch.object(esp32.weather_svc, "today", return_value=meteo), \
                mock.patch.object(esp32.spotify_svc, "now_playing",
                                  return_value=None):
            client = self.app.test_client()
            self.assertEqual(client.get("/api/esp32/pages").status_code, 401)
            r = client.get("/api/esp32/pages?key=cle-de-test")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(sorted(data), ["agenda", "jour", "meteo", "min",
                                        "ok", "sec", "spotify"])
        self.assertEqual(data["meteo"]["court"], "FAIBLE")
        self.assertNotIn("label", data["meteo"])
        self.assertEqual(data["spotify"], {"device": ""})
        self.assertLess(len(r.data), 2500)

    def test_latin(self):
        self.assertEqual(
            esp32._latin("Déjeuner  chez  Zoë, señor – 20 h \U0001f37d"),
            "Déjeuner chez Zoë, senor - 20 h")
        self.assertEqual(esp32._dans(45), "DANS 45 MIN")
        self.assertEqual(esp32._dans(120), "DANS 2 H")


if __name__ == "__main__":
    unittest.main()
