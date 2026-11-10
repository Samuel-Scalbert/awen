"""La dictée : une phrase dite au téléphone devient un évènement d'agenda.

    python -m unittest tests.test_dictee
"""
import unittest
from datetime import date, datetime
from unittest import mock

from app import create_app
from app.config import Config
from app.models import Todo, db
from app.services import agenda_google, dictee

# Mardi 10 novembre 2026, 15 h 27 : le jour de la demande.
MAINTENANT = datetime(2026, 11, 10, 15, 27)


def lu(phrase, maintenant=MAINTENANT):
    r = dictee.analyser(phrase, maintenant)
    return r["titre"], dictee.libelle(r["debut"], r["jour"], maintenant.date())


class AnalyseTest(unittest.TestCase):
    def test_la_phrase_de_samuel(self):
        self.assertEqual(lu("répondre à 18h au mail de conseil"),
                         ("Répondre au mail de conseil", "aujourd'hui à 18h"))

    def test_une_heure_passee_vaut_pour_demain(self):
        self.assertEqual(lu("répondre à 14h au mail de conseil"),
                         ("Répondre au mail de conseil", "demain à 14h"))

    def test_les_jours(self):
        self.assertEqual(lu("demain à 9h30 appeler la banque"),
                         ("Appeler la banque", "demain à 9h30"))
        self.assertEqual(lu("rappelle-moi d'envoyer le CV lundi à 14 heures"),
                         ("Envoyer le CV", "lundi 16 novembre à 14h"))
        self.assertEqual(lu("le 15 novembre à 10h rendez-vous dentiste"),
                         ("Rendez-vous dentiste", "dimanche 15 novembre à 10h"))
        # « le 3 » est passé ce mois-ci : c'est le 3 du mois prochain.
        self.assertEqual(lu("rendez-vous chez le dentiste le 3 à 11h"),
                         ("Rendez-vous chez le dentiste", "jeudi 3 décembre à 11h"))
        self.assertEqual(lu("Payer le loyer le 1er décembre"),
                         ("Payer le loyer", "mardi 1er décembre, toute la journée"))

    def test_un_jour_sans_heure_prend_la_journee(self):
        self.assertEqual(lu("jeudi faire la lessive"),
                         ("Faire la lessive", "jeudi 12 novembre, toute la journée"))
        self.assertEqual(lu("envoyer la note de frais vendredi"),
                         ("Envoyer la note de frais", "vendredi 13 novembre, toute la journée"))

    def test_les_heures_dites(self):
        self.assertEqual(lu("à 6h du soir appeler Paul"), ("Appeler Paul", "aujourd'hui à 18h"))
        self.assertEqual(lu("à 9h et demie réunion d'équipe"),
                         ("Réunion d'équipe", "demain à 9h30"))
        self.assertEqual(lu("à 7 heures moins le quart réveil"), ("Réveil", "demain à 6h45"))
        self.assertEqual(lu("18 h 30 match de volley"), ("Match de volley", "aujourd'hui à 18h30"))
        self.assertEqual(lu("ajoute à mon agenda déjeuner avec Léa demain midi"),
                         ("Déjeuner avec Léa", "demain à 12h"))

    def test_dans_un_moment(self):
        self.assertEqual(lu("dans 2 heures sortir le linge"),
                         ("Sortir le linge", "aujourd'hui à 17h27"))
        self.assertEqual(lu("dans une demi-heure relancer le four"),
                         ("Relancer le four", "aujourd'hui à 15h57"))
        self.assertEqual(lu("dans 1h30 récupérer le colis"),
                         ("Récupérer le colis", "aujourd'hui à 16h57"))

    def test_les_moments_de_la_journee(self):
        self.assertEqual(lu("appeler maman ce soir"), ("Appeler maman", "aujourd'hui à 20h"))
        self.assertEqual(lu("ajouter le logo au site demain matin"),
                         ("Ajouter le logo au site", "demain à 9h"))
        # « ce soir » dit à 21 h : encore ce soir, au prochain quart d'heure.
        self.assertEqual(lu("appeler maman ce soir", datetime(2026, 11, 10, 21, 5)),
                         ("Appeler maman", "aujourd'hui à 21h15"))

    def test_sans_date_c_est_une_tache(self):
        self.assertEqual(lu("acheter 2 baguettes"), ("Acheter 2 baguettes", "sans date"))


class ConfigTest(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"


class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(ConfigTest)

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        Todo.query.delete()
        db.session.commit()
        self.client = self.app.test_client()
        for nom, valeur in (("actif", True), ("poser", "evt123"), ("enlever", None)):
            p = mock.patch.object(agenda_google, nom, return_value=valeur)
            setattr(self, nom, p.start())
            self.addCleanup(p.stop)

    def test_la_page_s_installe(self):
        page = self.client.get("/dictee/").get_data(as_text=True)
        self.assertIn('rel="manifest"', page)
        self.assertIn("dictee.js", page)
        m = self.client.get("/dictee/manifest.webmanifest")
        self.assertEqual(m.mimetype, "application/manifest+json")
        data = m.get_json(force=True)
        self.assertEqual(data["start_url"], "/dictee/?auto=1")
        self.assertEqual(data["display"], "standalone")
        self.assertEqual({i["sizes"] for i in data["icons"]}, {"192x192", "512x512"})
        for icone in data["icons"]:
            self.assertEqual(self.client.get(icone["src"]).status_code, 200)

    def test_analyser(self):
        r = self.client.post("/dictee/analyser",
                             json={"texte": "répondre à 18h au mail de conseil"}).get_json()
        self.assertEqual(r["titre"], "Répondre au mail de conseil")
        self.assertRegex(r["quand"], r"^\d{4}-\d\d-\d\dT18:00$")
        self.assertEqual(self.client.post("/dictee/analyser", json={"texte": " "}).status_code, 400)

    def test_ajouter_a_l_agenda_puis_annuler(self):
        r = self.client.post("/dictee/ajouter", json={
            "titre": "Répondre au mail de conseil", "quand": "2026-11-10T18:00", "jour": ""}).get_json()
        self.assertEqual((r["type"], r["id"]), ("evenement", "evt123"))
        self.poser.assert_called_once_with("Répondre au mail de conseil",
                                           debut=datetime(2026, 11, 10, 18, 0), jour=None,
                                           description="Dicté dans Awen.")
        self.assertEqual(Todo.query.count(), 0)
        self.client.post("/dictee/annuler", json={"type": "evenement", "id": "evt123"})
        self.enlever.assert_called_once_with("evt123")

    def test_toute_la_journee(self):
        self.client.post("/dictee/ajouter", json={
            "titre": "Faire la lessive", "quand": "", "jour": "2026-11-12"})
        self.poser.assert_called_once_with("Faire la lessive", debut=None,
                                           jour=date(2026, 11, 12), description="Dicté dans Awen.")

    def test_sans_date_dans_les_taches(self):
        r = self.client.post("/dictee/ajouter", json={
            "titre": "Acheter du pain", "quand": "", "jour": ""}).get_json()
        self.assertEqual(r["type"], "tache")
        self.poser.assert_not_called()
        t = Todo.query.one()
        self.assertEqual((t.text, t.source, t.due), ("Acheter du pain", "dictee", None))
        self.client.post("/dictee/annuler", json={"type": "tache", "id": t.id})
        self.assertEqual(Todo.query.count(), 0)

    def test_google_muet_rien_ne_se_perd(self):
        self.poser.side_effect = OSError("réseau")
        r = self.client.post("/dictee/ajouter", json={
            "titre": "Répondre au mail de conseil", "quand": "2026-11-10T18:00", "jour": ""}).get_json()
        self.assertEqual(r["type"], "tache")
        self.assertIn("Google Agenda n'a pas répondu", r["message"])
        t = Todo.query.one()
        self.assertEqual((t.text, t.due), ("Répondre au mail de conseil (18h)", date(2026, 11, 10)))

    def test_l_annulation_ne_touche_pas_les_autres_taches(self):
        t = Todo(text="Écrite à la main", source="web")
        db.session.add(t)
        db.session.commit()
        self.client.post("/dictee/annuler", json={"type": "tache", "id": t.id})
        self.assertEqual(Todo.query.count(), 1)


if __name__ == "__main__":
    unittest.main()
