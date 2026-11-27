"""Les récaps de fin de session Claude Code : /api/dev.

    python -m unittest tests.test_dev_recap
"""
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import create_app
from app.config import Config
from app.services import dev_recap

CLE = "cle-de-test"


class ConfigTest(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    DEV_API_KEY = CLE


class DevRecapTest(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix="awen-recaps-"))
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        ConfigTest.DEV_RECAP_DIR = str(self.dossier)
        self.app = create_app(ConfigTest)
        self.client = self.app.test_client()

    def poster(self, corps, cle=CLE):
        return self.client.post("/api/dev/recap", json=corps, headers={"X-API-Key": cle})

    def test_la_cle(self):
        self.assertEqual(self.poster({"project": "awen"}, cle="mauvaise").status_code, 401)
        self.assertEqual(self.client.get("/api/dev/board").status_code, 401)
        self.assertEqual(self.client.get("/api/dev/board?key=" + CLE).status_code, 200)

    def test_sans_cle_configuree_tout_est_ferme(self):
        for valeur in ("", "change-me"):
            self.app.config["DEV_API_KEY"] = valeur
            r = self.client.get("/api/dev/board?key=change-me")
            self.assertEqual(r.status_code, 503, valeur)

    def test_un_recap_puis_le_tableau(self):
        r = self.poster({"project": "awen", "branch": "main", "dirty": 3,
                         "stopped_at": "plafond des levees pousse",
                         "next": ["  tester la collecte   BODACC sur le serveur ", 42, ""],
                         "blockers": [], "inconnu": "ignore"})
        self.assertEqual(r.status_code, 201)
        recap = r.get_json()
        self.assertEqual(recap["next"], ["tester la collecte BODACC sur le serveur"])
        self.assertNotIn("inconnu", recap)
        self.assertTrue((self.dossier / "awen.json").exists())
        tableau = self.client.get("/api/dev/board?key=" + CLE).get_data(as_text=True)
        self.assertTrue(tableau.startswith("awen · main · 3 fich."))
        self.assertIn("-> tester la collecte BODACC", tableau)
        self.assertTrue(all(len(l) <= 34 for l in tableau.splitlines()))
        # Un second récap du même projet écrase le premier.
        self.poster({"project": "awen", "next": []})
        self.assertEqual(len(self.client.get("/api/dev/recaps?key=" + CLE).get_json()), 1)
        self.assertIn("rien en cours", self.client.get("/api/dev/board?key=" + CLE).get_data(as_text=True))

    def test_un_nom_de_projet_qui_sortirait_du_dossier(self):
        for nom in ("../evil", "a/b", "", None, "x" * 65):
            self.assertEqual(self.poster({"project": nom}).status_code, 422, nom)
        self.assertEqual(list(self.dossier.iterdir()), [])

    def test_perime_et_fichier_casse(self):
        vieux = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        (self.dossier / "asvp.json").write_text(json.dumps({"project": "asvp", "updated": vieux}), encoding="utf-8")
        (self.dossier / "casse.json").write_text("{pas du json", encoding="utf-8")
        with self.app.app_context():
            recaps = dev_recap.load_recaps()
        self.assertEqual([r["project"] for r in recaps], ["asvp"])
        self.assertTrue(recaps[0]["stale"])
        self.assertIn("asvp · perime", self.client.get("/api/dev/board?key=" + CLE).get_data(as_text=True))

    def test_les_taches_reviennent_a_la_ligne(self):
        self.poster({"project": "awen", "branch": "main",
                     "next": ["Mettre a jour le clone de septembre avant de toucher aux hooks"],
                     "blockers": ["Coach et pesees : " + "tres long " * 20]})
        tableau = self.client.get("/api/dev/board?key=" + CLE).get_data(as_text=True)
        lignes = tableau.splitlines()
        self.assertTrue(all(len(l) <= 34 for l in lignes), lignes)
        # La tâche se lit en entier, ses suites alignées sous le texte.
        self.assertEqual(lignes[1:4], ["  -> Mettre a jour le clone de",
                                       "     septembre avant de toucher",
                                       "     aux hooks"])
        # Un point trop long s'arrête à trois lignes.
        blocage = [l for l in lignes if l.startswith("  !! ")]
        self.assertEqual(len(lignes[lignes.index(blocage[0]):]), 3)
        self.assertTrue(lignes[-1].endswith(".."))

    def test_la_largeur(self):
        self.poster({"project": "awen", "next": ["Mettre a jour le clone de septembre avant de toucher aux hooks"]})
        large = self.client.get("/api/dev/board?largeur=80&key=" + CLE).get_data(as_text=True)
        self.assertIn("  -> Mettre a jour le clone de septembre avant de toucher aux hooks", large)
        etroit = self.client.get("/api/dev/board?largeur=5&key=" + CLE).get_data(as_text=True)
        self.assertTrue(all(len(l) <= 20 for l in etroit.splitlines()))      # ramené au minimum
        self.assertEqual(self.client.get("/api/dev/board?largeur=abc&key=" + CLE).status_code, 200)

    def test_aucun_recap(self):
        self.assertIn("Aucun recap", self.client.get("/api/dev/board?key=" + CLE).get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
