"""Le journal de l'afficheur : pourquoi la carte a redémarré.

    python -m unittest tests.test_journal

La carte joint son état à chaque relevé de /pages et annonce la cause de
son démarrage. Le serveur doit ranger la cause à côté du DERNIER état d'avant
le redémarrage, pas du premier relevé qui le suit.
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import create_app
from app.config import Config
from app.routes import esp32 as esp32_routes


class ConfigTest(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    ESP32_API_KEY = "cle"


class JournalTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(ConfigTest)

    def setUp(self):
        dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, dossier, True)
        self.journal = Path(dossier) / "esp32-journal.log"
        self.app.config["ESP32_JOURNAL"] = str(self.journal)
        esp32_routes._carte.clear()
        # /pages interroge Spotify, la météo et l'agenda : rien de tout cela
        # ne compte ici, seul l'état joint à l'adresse nous intéresse.
        for nom in ("_weather_pages", "_agenda_block", "_spotify_block"):
            p = mock.patch.object(esp32_routes, nom, return_value={})
            p.start()
            self.addCleanup(p.stop)
        self.client = self.app.test_client()

    def _releve(self, up, mem, page="spotify"):
        r = self.client.get("/api/esp32/pages?key=cle&up={}&mem={}&idf=40000"
                            "&bas=9000&p={}&e=0&n=2".format(up, mem, page))
        self.assertEqual(r.status_code, 200)

    def _lignes(self):
        r = self.client.get("/api/esp32/journal?key=cle")
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def test_la_cause_va_avec_l_etat_d_avant(self):
        self._releve(7200, 61000)
        self._releve(7205, 60500)
        # La carte redémarre : son premier relevé repart de zéro, puis elle
        # annonce la cause.
        self._releve(20, 90000, "home")
        r = self.client.post("/api/esp32/journal?key=cle",
                             json={"evt": "demarrage", "cause": "ALIM",
                                   "up": 21, "mem": 89000})
        self.assertEqual(r.status_code, 200)

        d = self._lignes()
        ligne = d["journal"][-1]
        self.assertEqual(ligne["evt"], "demarrage")
        self.assertEqual(ligne["cause"], "ALIM")
        self.assertEqual(ligne["avant"]["up"], 7205)
        self.assertEqual(ligne["avant"]["mem"], 60500)
        self.assertEqual(ligne["avant"]["p"], "spotify")
        self.assertEqual(d["etat"]["up"], 20)

    def test_sans_relevé_d_avant(self):
        """Le serveur a redémarré lui aussi : on le dit, sans inventer."""
        self.client.post("/api/esp32/journal?key=cle",
                         json={"evt": "demarrage", "cause": "LOGICIEL"})
        self.assertIsNone(self._lignes()["journal"][-1]["avant"])

    def test_erreur_de_la_boucle(self):
        self.client.post("/api/esp32/journal?key=cle",
                         json={"evt": "erreur", "msg": "MemoryError  (spotify)",
                               "up": 300, "mem": 4000})
        ligne = self._lignes()["journal"][-1]
        self.assertEqual(ligne["msg"], "MemoryError  (spotify)")
        self.assertNotIn("avant", ligne)

    def test_ancien_firmware(self):
        """Un relevé sans état ne casse rien et n'efface pas le dernier."""
        self._releve(50, 70000)
        self.assertEqual(self.client.get("/api/esp32/pages?key=cle")
                         .status_code, 200)
        self.assertEqual(self._lignes()["etat"]["up"], 50)

    def test_cle_exigee(self):
        self.assertEqual(self.client.get("/api/esp32/journal").status_code, 401)
        self.assertEqual(self.client.post("/api/esp32/journal", json={})
                         .status_code, 401)

    def test_le_fichier_ne_grossit_pas_sans_fin(self):
        with mock.patch.object(esp32_routes, "JOURNAL_MAX", 2000):
            for i in range(100):
                self.client.post("/api/esp32/journal?key=cle",
                                 json={"evt": "erreur", "msg": "x" * 40})
        self.assertLess(self.journal.stat().st_size, 2200)
        # Chaque ligne restante est entière.
        self.assertTrue(all(x["evt"] == "erreur"
                            for x in self._lignes()["journal"]))


if __name__ == "__main__":
    unittest.main()
