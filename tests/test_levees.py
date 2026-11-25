"""Les levées de fonds : la collecte, les dirigeants, le mail de prospection.

    python -m unittest tests.test_levees

Rien ne sort sur le réseau : les pages de Maddyness, le registre, le site
de l'entreprise et Claude sont remplacés par des fixtures.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import create_app
from app.config import Config
from app.models import CollecteLevees, Levee, MailProspection, db
from app.services import levees

RECAP = {"date": "2026-11-13", "lien": "https://www.maddyness.com/2026/11/13/recap/",
         "titre": "Les startups françaises ont levé 118 millions d'euros cette semaine"}

PAGE_RECAP = """<html><body>
<p>Avec 118 millions d'euros réunis, la semaine est forte. Nuage Logiciel signe la plus belle opération
avec 4 millions d'euros auprès de Alpha Capital pour son outil de tests. Ferme Bio suit.</p>
<h2>Voici les levées de fonds de cette semaine :</h2>
<div class="financements"> <div class="financements__item"> <div class="financements__hashtag"> <span>#IT</span> </div>
<a class="financements__name js-x" data-enterprise="nuage-logiciel" href="https://www.maddyness.com/entreprise/nuage-logiciel/" title="Nuage Logiciel"> Nuage Logiciel </a>
<div class="financements__amount"> 4.0 M€ </div> <div class="financements__text">
<a title="Alpha Capital" href="https://www.maddyness.com/base-fonds-investissements/alpha-capital/"> Alpha Capital </a>, <a href="https://www.maddyness.com/base-fonds-investissements/ba/"> business angels, </a></div></div>
<div class="financements__item"> <div class="financements__hashtag"> <span>#agritech</span> </div>
<a class="financements__name" href="https://www.maddyness.com/entreprise/ferme-bio/" title="Ferme Bio"> Ferme Bio </a>
<div class="financements__amount"> 1.5 M€ </div> <div class="financements__text"></div></div></div>
</body></html>"""

FICHE_NUAGE = """<html><body><p>Alpha Capital</p> Siège social <span>Paris</span> Créé en <span>2024</span>
Ils recrutent <a href="https://www.youtube.com/c/Maddynessvideo">vidéo</a> <a href="https://www.nuage-logiciel.fr/">site</a></body></html>"""
FICHE_FERME = """<html><body> Siège social <span>Rennes</span> Créé en <span>2021</span>
<a href="https://fermebio.example/">site</a></body></html>"""

REGISTRE_NUAGE = {"results": [
    {"siren": "111222333", "nom_complet": "NUAGE LOGICIEL", "date_creation": "2024-03-01",
     "tranche_effectif_salarie": "11", "activite_principale": "62.01Z",
     "siege": {"libelle_commune": "PARIS", "code_postal": "75010"},
     "dirigeants": [
         {"type_dirigeant": "personne physique", "prenoms": "MARIE LOUISE", "nom": "DURAND (VERNET)", "qualite": "Président de SAS"},
         {"type_dirigeant": "personne physique", "prenoms": "PAUL", "nom": "MARTIN", "qualite": "Directeur Général"},
         {"type_dirigeant": "personne physique", "prenoms": "JEAN", "nom": "AUDIT", "qualite": "Commissaire aux comptes"},
         {"type_dirigeant": "personne morale", "denomination": "ALPHA CAPITAL", "qualite": "Directeur Général"}]},
    {"siren": "999", "nom_complet": "NUAGE", "date_creation": "2010-01-01", "tranche_effectif_salarie": "31",
     "siege": {"libelle_commune": "LYON", "code_postal": "69001"}, "dirigeants": []}]}

SITE_NUAGE = """<html><head><meta name="description" content="Nuage Logiciel teste vos applications sans écrire de test."></head>
<body><nav>Menu</nav><h1>Des tests sans effort</h1><p>Nous écrivons les tests à votre place.</p>
<footer>contact@nuage-logiciel.fr · <a href="/cdn-cgi/l/email-protection#1c71757e7e7d5c72697d7b797173737b7d7f7832767e">mail</a></footer>
<script>var x = "ignore@nuage-logiciel.fr";</script></body></html>"""
# « marie@nuage-logiciel.fr », masqué comme le fait Cloudflare (clé 0x1c).
CF = "1c" + "".join("{:02x}".format(ord(c) ^ 0x1c) for c in "marie@nuage-logiciel.fr")
SITE_NUAGE = SITE_NUAGE.replace("1c71757e7e7d5c72697d7b797173737b7d7f7832767e", CF)
SITE_JOBS = "<html><body>Écris à jobs@nuage-logiciel.fr</body></html>"

def _annonce(siren, nom, modif="modification survenue sur le capital (augmentation)", capital="3041.30"):
    return {"dateparution": "2026-11-20", "commercant": nom, "registre": [siren, siren],
            "modificationsgenerales": json.dumps({"descriptif": modif}),
            "listepersonnes": json.dumps({"personne": {"capital": {"montantCapital": capital, "devise": "EUR"}}}),
            "url_complete": "https://www.bodacc.fr/annonce/" + siren}


BODACC = {"total_count": 6, "results": [
    _annonce("444555666", "BRUME DATA"),
    _annonce("444555666", "BRUME DATA"),                                  # deux annonces, une entreprise
    _annonce("111111111", "SCI DES LILAS"),                               # pas une startup
    _annonce("222222222", "VIEUX LOGICIEL", modif="modification survenue sur le capital (diminution)"),
    _annonce("777888999", "FILIALE FRANCE"),                              # présidée par une société
    _annonce("333444555", "CONSEIL ET CIE")]}                             # conseil, pas logiciel
PAR_SIREN = {
    "444555666": {"siren": "444555666", "nom_complet": "BRUME DATA", "date_creation": "2024-05-02",
                  "tranche_effectif_salarie": "02", "activite_principale": "62.01Z",
                  "siege": {"libelle_commune": "PARIS", "code_postal": "75011"},
                  "dirigeants": [{"type_dirigeant": "personne physique", "prenoms": "LÉA", "nom": "ROUX",
                                  "qualite": "Président de SAS"}]},
    "777888999": {"siren": "777888999", "nom_complet": "FILIALE FRANCE", "date_creation": "2023-01-01",
                  "tranche_effectif_salarie": "03", "activite_principale": "62.01Z",
                  "siege": {"libelle_commune": "PARIS", "code_postal": "75008"},
                  "dirigeants": [{"type_dirigeant": "personne morale", "denomination": "MAISON MERE INC",
                                  "qualite": "Président"}]},
    "333444555": {"siren": "333444555", "nom_complet": "CONSEIL ET CIE", "date_creation": "2025-01-01",
                  "tranche_effectif_salarie": "NN", "activite_principale": "70.22Z",
                  "siege": {"libelle_commune": "PARIS", "code_postal": "75002"}, "dirigeants": []}}
SITE_PARKING = "<html><head><title>brumedata.com</title></head><body>This domain is for sale. Brume Data</body></html>"
SITE_BRUME = """<html><head><title>Brume</title></head><body><h1>Vos données, sans brouillard</h1>
<p>Une équipe de quatre personnes.</p><p>Mentions : SAS au capital de 3 041 €, RCS Paris 444 555 666.</p>
<p>Écrivez à lea@brumedata.fr</p></body></html>"""

BAN = {"Paris": {"features": [{"properties": {"context": "75, Paris, Île-de-France"}}]},
       "Rennes": {"features": [{"properties": {"context": "35, Ille-et-Vilaine, Bretagne"}}]}}


class Reponse:
    def __init__(self, text="", data=None):
        self.text, self._data, self.headers = text, data, {"content-type": "text/html; charset=utf-8"}

    def json(self):
        if self._data is None:
            raise ValueError("pas de JSON")
        return self._data


def faux_get(url, params=None, timeout=15, headers=None):
    """Le réseau, remplacé : chaque adresse connue rend sa fixture."""
    params = params or {}
    if url.startswith(levees.MADDY + "/wp-json"):
        return Reponse(data=[{"date": RECAP["date"] + "T07:00:00", "link": RECAP["lien"],
                              "title": {"rendered": RECAP["titre"]}}])
    if url == RECAP["lien"]:
        return Reponse(PAGE_RECAP)
    if "entreprise/nuage-logiciel" in url:
        return Reponse(FICHE_NUAGE)
    if "entreprise/ferme-bio" in url:
        return Reponse(FICHE_FERME)
    if url == levees.API_ADRESSE:
        return Reponse(data=BAN.get(params.get("q"), {"features": []}))
    if url == levees.API_ENT:
        q = params.get("q", "")
        if q in PAR_SIREN:
            return Reponse(data={"results": [PAR_SIREN[q]]})
        return Reponse(data=REGISTRE_NUAGE if "nuage" in q.lower() else {"results": []})
    if url == levees.BODACC:
        return Reponse(data=BODACC if params.get("offset", 0) == 0 else {"total_count": 6, "results": []})
    if url == "https://brumedata.com":
        return Reponse(SITE_PARKING)
    if url in ("https://brumedata.fr", "https://brumedata.fr/"):
        return Reponse(SITE_BRUME)
    if url == levees.DNS:
        return Reponse(data={"Answer": [{"data": "10 mx.example."}]}
                       if params.get("name") in ("nuage-logiciel.fr", "brumedata.fr") else {})
    if url.startswith("https://www.nuage-logiciel.fr/"):
        reste = url[len("https://www.nuage-logiciel.fr/"):]
        if reste == "":
            return Reponse(SITE_NUAGE)
        if reste == "jobs":
            return Reponse(SITE_JOBS)
    return None


class ConfigTest(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    ANTHROPIC_API_KEY = "cle-de-test"
    CLAUDE_CODE_OAUTH_TOKEN = ""
    LETTRE_MOTEUR = "auto"


MAIL = {"resume": "Nuage Logiciel écrit les tests à la place des développeurs.\nLevée de 4 M€ auprès d'Alpha Capital.\nDix à dix-neuf personnes, créée en 2024.\nSamuel y serait utile sur le cadrage produit.\nVérifier le format de l'adresse.",
        "objet": "Vos tests après la levée",
        "paragraphes": ["Vous venez de lever 4 M€ pour écrire les tests à la place des développeurs.",
                        "Je construis Awen en pilotant Claude Code — 119 commits en quatre mois.",
                        "Auriez-vous quinze minutes cette semaine ?"],
        "notes": "Preuve choisie : Awen.\nÀ vérifier : le prénom du destinataire."}


class CollecteTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(ConfigTest)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        p = mock.patch.object(levees, "get", side_effect=faux_get)
        p.start()
        self.addCleanup(p.stop)
        levees._DEPS.clear()

    def test_les_operations_du_recapitulatif(self):
        ops = levees.operations(RECAP)
        self.assertEqual([o["entreprise"] for o in ops], ["Nuage Logiciel", "Ferme Bio"])
        o = ops[0]
        self.assertEqual((o["montant"], o["secteur"], o["semaine"]), ("4.0 M€", "IT", "2026-11-13"))
        self.assertEqual(o["investisseurs"], "Alpha Capital, business angels")
        self.assertIn("4 millions d'euros auprès de Alpha Capital", o["contexte"])
        self.assertNotIn("Ferme Bio suit", o["contexte"])

    def test_la_fiche_et_le_registre(self):
        op = levees.operations(RECAP)[0]
        levees.fiche(op)
        self.assertEqual((op["ville"], op["creee"], op["site"], op["recrute"], op["departement"]),
                         ("Paris", "2024", "https://www.nuage-logiciel.fr/", True, "75"))
        levees.registre(op)
        self.assertEqual((op["registre"], op["siren"], op["effectif"], op["effectif_max"]),
                         ("ok", "111222333", "10-19", 19))
        # Le président d'abord, les commissaires aux comptes et les personnes
        # morales jamais ; le nom perd sa parenthèse.
        self.assertEqual([(d["prenom"], d["nom"], d["qualite"]) for d in op["dirigeants"]],
                         [("Marie", "Durand", "Président de SAS"), ("Paul", "Martin", "Directeur Général")])

    def test_les_adresses_du_site(self):
        op = {"entreprise": "Nuage Logiciel", "site": "https://www.nuage-logiciel.fr/",
              "dirigeants": [{"prenom": "Marie", "nom": "Durand", "qualite": "Président de SAS", "adresses": []},
                             {"prenom": "Paul", "nom": "Martin", "qualite": "Directeur Général", "adresses": []}]}
        levees.adresses_du_site(op)
        self.assertEqual(op["domaine"], "nuage-logiciel.fr")
        self.assertEqual(op["pitch"], "Nuage Logiciel teste vos applications sans écrire de test.")
        self.assertIn("Nous écrivons les tests", op["texte_site"])
        self.assertNotIn("Menu", op["texte_site"])               # la navigation reste dehors
        self.assertEqual(op["adresses_generiques"], ["contact@nuage-logiciel.fr"])
        self.assertEqual(op["adresses_recrutement"], ["jobs@nuage-logiciel.fr"])
        self.assertEqual(op["adresses_nominatives"], ["marie@nuage-logiciel.fr"])   # décodée de Cloudflare
        self.assertEqual(op["format_adresse"], "prenom")
        levees.adresses_probables(op)
        self.assertEqual(op["mx"], "oui")
        # Le site a montré le format : une seule adresse par dirigeant.
        self.assertEqual(op["dirigeants"][0]["adresses"], ["marie@nuage-logiciel.fr"])
        self.assertEqual(op["dirigeants"][1]["adresses"], ["paul@nuage-logiciel.fr"])
        self.assertEqual(levees.priorite(op), 3 + 1)              # recrute, quelqu'un à qui écrire

    def test_sans_format_connu_deux_adresses(self):
        op = {"domaine": "ex.fr", "dirigeants": [{"prenom": "Noé", "nom": "Le Bihan", "qualite": "Président", "adresses": []}]}
        with mock.patch.object(levees, "mx", return_value=False):
            levees.adresses_probables(op)
        self.assertEqual(op["dirigeants"][0]["adresses"], ["noe@ex.fr", "noe.lebihan@ex.fr"])
        self.assertEqual(op["mx"], "non")

    def test_la_collecte_garde_l_ile_de_france_et_dedoublonne(self):
        retenues, ecartees = levees.collecter(4, montant_max=None, equipe_max=None, sources=("maddyness",))
        self.assertEqual([o["entreprise"] for o in retenues], ["Nuage Logiciel"])
        self.assertEqual([(o["entreprise"], r) for o, r in ecartees], [("Ferme Bio", "hors Île-de-France (Rennes)")])
        self.assertEqual(levees.enregistrer(retenues), 1)
        l = Levee.query.one()
        # Priorité 7 : recrute (3), secteur IT (2), moins de 50 personnes (1), quelqu'un à qui écrire (1).
        self.assertEqual((l.entreprise, l.montant, l.ville, l.effectif, l.priorite), ("Nuage Logiciel", "4.0 M€", "Paris", "10-19", 7))
        self.assertEqual(l.dirigeants_liste[0]["adresses"], ["marie@nuage-logiciel.fr"])
        self.assertEqual(l.destinataires[0], "Marie Durand (Président de SAS) <marie@nuage-logiciel.fr>")
        # Une seconde collecte rafraîchit les faits et garde le statut.
        l.statut, l.notes = "contactee", "écrit le 16/11"
        db.session.commit()
        self.assertEqual(levees.enregistrer(retenues), 0)
        l = Levee.query.one()
        self.assertEqual((l.statut, l.notes), ("contactee", "écrit le 16/11"))

    def test_la_collecte_en_arriere_plan(self):
        with mock.patch.object(levees, "lancer", side_effect=lambda f, i: f(i)):
            c = levees.lancer_collecte(2, "0", "0", ["maddyness"])
        self.assertEqual((c.etat, c.nb_operations, c.nb_nouvelles), ("terminee", 2, 1))
        self.assertEqual((c.montant_max, c.equipe_max, c.sources), (None, None, "maddyness"))
        self.assertIn("1 nouvelle", c.message)
        self.assertIn("1 (hors IDF)", c.message)
        self.assertEqual(Levee.query.count(), 1)

    def test_les_reglages_par_defaut(self):
        """500 k€, moins de 20 personnes, les deux sources ; une valeur
        illisible garde le défaut, « 0 » lève la limite."""
        with mock.patch.object(levees, "lancer"):
            c = levees.lancer_collecte(4, None, "n'importe quoi", [])
        self.assertEqual((c.montant_max, c.equipe_max, c.sources), (500000, 19, "maddyness,bodacc"))

    def test_le_plafond_de_montant_avant_le_registre(self):
        with mock.patch.object(levees, "fiche") as fiche:
            retenues, ecartees = levees.collecter(4, sources=("maddyness",))
        self.assertEqual(retenues, [])
        self.assertEqual([r for _, r in ecartees], ["levée de 4.0 M€", "levée de 1.5 M€"])
        fiche.assert_not_called()                                 # aucune requête perdue
        self.assertEqual((levees.euros("400.0 k€"), levees.euros("1.5 M€"), levees.euros("")),
                         (400000, 1500000, None))

    def test_le_plafond_d_equipe(self):
        retenues, ecartees = levees.collecter(4, montant_max=None, equipe_max=9, sources=("maddyness",))
        self.assertEqual(retenues, [])
        self.assertIn(("Nuage Logiciel", "effectif 10-19"), [(o["entreprise"], r) for o, r in ecartees])

    def test_le_bodacc(self):
        retenues, ecartees = levees.collecter(2, sources=("bodacc",))
        # Ni la SCI, ni la baisse de capital, ni la filiale, ni le cabinet de conseil.
        self.assertEqual([o["entreprise"] for o in retenues], ["Brume Data"])
        o = retenues[0]
        self.assertEqual((o["source"], o["montant"], o["secteur"], o["effectif"], o["ville"], o["creee"]),
                         ("bodacc", "", "logiciel", "3-5", "Paris", "2024"))
        self.assertEqual((o["capital"], o["semaine"]), ("3 041 €", "2026-11-20"))
        # Le .com est une page parking ; le .fr porte le SIREN dans ses mentions.
        self.assertEqual(o["site"], "https://brumedata.fr")
        self.assertIn("Site vérifié", o["contexte"])
        self.assertEqual(o["dirigeants"][0]["adresses"], ["lea@brumedata.fr"])
        self.assertEqual(levees.enregistrer(retenues), 1)
        l = Levee.query.one()
        self.assertEqual((l.source, l.annonce), ("bodacc", "https://www.bodacc.fr/annonce/444555666"))
        # Une entreprise déjà en base n'est pas relue.
        self.assertEqual(levees.collecter(2, sources=("bodacc",), deja_vus={"444555666"}), ([], []))

    def test_les_noms_lisibles(self):
        self.assertEqual(levees.nom_lisible("DOYE (QWOTY)"), "Qwoty")
        self.assertEqual(levees.nom_lisible("MACRODATA LABS"), "Macrodata Labs")
        self.assertEqual(levees.nom_lisible("HERACLES AI"), "Heracles AI")
        self.assertEqual(levees.nom_lisible("Shaarp"), "Shaarp")
        self.assertEqual(levees._candidats_site("Prettywhale.ai"), ["https://prettywhale.ai"])


# Les fixtures Maddyness sont de grosses levées (4 et 1,5 M€) : les tests de
# page collectent sans plafond.
SANS_PLAFOND = {"semaines": "4", "montant_max": "0", "equipe_max": "0", "sources": "maddyness"}


class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dossier = Path(tempfile.mkdtemp(prefix="awen-levees-"))
        (cls.dossier / "Fiche profil - Samuel Scalbert.md").write_text("# Fiche profil\n\nHistorien devenu ingénieur data.", encoding="utf-8")
        (cls.dossier / "_CV ATS (source modifiable).html").write_text("<html><body><h1>Samuel</h1></body></html>", encoding="utf-8")
        ConfigTest.JOB_SEARCH_DIR = str(cls.dossier)
        cls.app = create_app(ConfigTest)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dossier, ignore_errors=True)

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        MailProspection.query.delete()
        Levee.query.delete()
        CollecteLevees.query.delete()
        db.session.commit()
        self.client = self.app.test_client()
        for nom, side in (("get", faux_get), ("lancer", lambda f, i: f(i))):
            p = mock.patch.object(levees, nom, side_effect=side)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(levees.lettres, "_appel", return_value=(MAIL, {"modele": "claude-opus-5-5", "entree": 3000, "sortie": 400}))
        self.appel = p.start()
        self.addCleanup(p.stop)

    def test_le_bouton_collecte_puis_la_liste(self):
        page = self.client.get("/jobs/levees").get_data(as_text=True)
        self.assertIn("Lancer la collecte", page)
        r = self.client.post("/jobs/levees/collecter", data=SANS_PLAFOND)
        self.assertEqual(r.status_code, 302)
        etat = self.client.get("/jobs/levees/etat").get_json()
        self.assertEqual(etat["etat"], "terminee")
        page = self.client.get("/jobs/levees").get_data(as_text=True)
        self.assertIn("Nuage Logiciel", page)
        self.assertIn("marie@nuage-logiciel.fr", page)
        self.assertIn("Alpha Capital", page)
        self.assertNotIn("Ferme Bio", page)
        l = Levee.query.one()
        self.client.post("/jobs/levees/{}/statut".format(l.id), data={"statut": "ecartee"})
        self.assertEqual(Levee.query.one().statut, "ecartee")

    def test_le_mail_puis_l_envoi(self):
        self.client.post("/jobs/levees/collecter", data=SANS_PLAFOND)
        l = Levee.query.one()
        r = self.client.post("/jobs/levees/{}/mail".format(l.id), data={
            "destinataire": l.destinataires[0], "consigne": "Parle d'Awen"})
        self.assertEqual(r.status_code, 302)
        m = MailProspection.query.one()
        self.assertEqual(m.etat, "pret")
        # Ce que Claude a reçu : l'entreprise, son site, le destinataire, la consigne, le skill.
        systeme, demande = self.appel.call_args[0][0], self.appel.call_args[0][1]
        self.assertIn("Mail de prospection", systeme)
        self.assertIn("Historien devenu ingénieur data", systeme)
        self.assertIn("Nous écrivons les tests", demande)
        self.assertIn("Marie Durand", demande)
        self.assertIn("Parle d'Awen", demande)
        self.assertEqual(self.appel.call_args[0][3], "medium")
        # Le tiret long de Claude est remplacé, le résumé et les notes sont gardés.
        self.assertNotIn("—", m.corps)
        self.assertIn("Claude Code, 119 commits", m.corps)
        self.assertEqual(m.objet, "Vos tests après la levée")
        self.assertIn("Alpha Capital", m.resume)
        page = self.client.get("/jobs/levees/mails/{}".format(m.id)).get_data(as_text=True)
        self.assertIn("Copier le mail", page)
        self.assertIn("L'entreprise, en cinq lignes", page)
        self.assertEqual(self.client.get("/jobs/levees/mails/{}/etat".format(m.id)).get_json()["etat"], "pret")
        # On corrige, puis on marque envoyé : l'entreprise passe en contactée.
        r = self.client.post("/jobs/levees/mails/{}/enregistrer".format(m.id), json={
            "objet": "Vos tests, après la levée", "corps": "Bonjour.", "signature": "Samuel\n06 00"})
        self.assertEqual(r.get_json()["mots"], 1)
        self.client.post("/jobs/levees/mails/{}/envoye".format(m.id))
        m = MailProspection.query.one()
        self.assertIsNotNone(m.envoye_le)
        self.assertEqual(m.levee.statut, "contactee")
        self.assertEqual(levees.texte_mail(m), "Bonjour.\n\nSamuel\n06 00")
        # Le mail suivant reprend la signature corrigée.
        self.client.post("/jobs/levees/{}/mail".format(l.id), data={"destinataire": "<contact@nuage-logiciel.fr>"})
        self.assertEqual(MailProspection.query.order_by(MailProspection.id.desc()).first().signature, "Samuel\n06 00")

    def test_les_plafonds_masquent_les_grosses_levees(self):
        self.client.post("/jobs/levees/collecter", data=SANS_PLAFOND)
        page = self.client.get("/jobs/levees").get_data(as_text=True)
        self.assertIn("Nuage Logiciel", page)
        self.assertIn('value="500000" selected', page)                   # le formulaire part de 500 k€
        # Une collecte BODACC avec les réglages par défaut : Brume Data entre,
        # Nuage Logiciel (4 M€) se cache, sauf à tout afficher.
        self.client.post("/jobs/levees/collecter", data={"semaines": "2", "sources": "bodacc"})
        page = self.client.get("/jobs/levees").get_data(as_text=True)
        self.assertIn("Brume Data", page)
        self.assertIn("montant inconnu", page)
        self.assertIn("annonce BODACC", page)
        self.assertNotIn("Nuage Logiciel", page)
        self.assertIn("1 entreprise au-dessus des plafonds", page)
        self.assertIn("Nuage Logiciel", self.client.get("/jobs/levees?tout=1").get_data(as_text=True))
        # Une conversation engagée ne se cache jamais.
        nuage = Levee.query.filter_by(entreprise="Nuage Logiciel").one()
        nuage.statut = "contactee"
        db.session.commit()
        self.assertIn("Nuage Logiciel", self.client.get("/jobs/levees").get_data(as_text=True))
        # Le mail d'une entreprise BODACC ne donne ni montant ni investisseurs à Claude.
        brume = Levee.query.filter_by(entreprise="Brume Data").one()
        self.client.post("/jobs/levees/{}/mail".format(brume.id), data={"destinataire": brume.destinataires[0]})
        demande = self.appel.call_args[0][1]
        self.assertIn("Source : BODACC", demande)
        self.assertNotIn("Levée :", demande)
        self.assertIn("Quand la source est le BODACC", self.appel.call_args[0][0])

    def test_claude_en_panne(self):
        self.client.post("/jobs/levees/collecter", data=SANS_PLAFOND)
        l = Levee.query.one()
        self.appel.side_effect = levees.LettreErreur("Ton abonnement Claude a atteint sa limite")
        self.client.post("/jobs/levees/{}/mail".format(l.id), data={"destinataire": "x <a@b.fr>"})
        m = MailProspection.query.one()
        self.assertEqual(m.etat, "erreur")
        page = self.client.get("/jobs/levees/mails/{}".format(m.id)).get_data(as_text=True)
        self.assertIn("atteint sa limite", page)
        self.assertIn("Réessayer", page)


if __name__ == "__main__":
    unittest.main()
