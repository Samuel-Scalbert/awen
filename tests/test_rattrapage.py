"""Rattraper une offre que la veille a écartée à tort.

    python -m unittest tests.test_rattrapage

Le cas d'origine, le 10/11/2026 : « Product Owner / Business Analyst Finance
F/H, INOCO », écartée pour « plus de 5 ans exigés » lus dans l'en-tête de
Welcome to the Jungle, quand l'annonce dit « > 3-5 ans ».
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import create_app
from app.config import Config
from app.models import CoverLetter, OffreRattrapee, db
from app.services import lettres, rattrapage

LIEN = ("https://www.welcometothejungle.com/fr/companies/inoco/jobs/"
        "product-owner-business-analyst-financef-h_paris_INOCO_JDaV46R")

COMPTE_RENDU = """# Veille du 10 novembre 2026

## Offres retenues

### 1. Product Manager IA (produits GenAI), INOCO

- **Entreprise** : INOCO
- **Verdict** : Postuler aujourd'hui

**Fit** : bon.

## Offres examinées et écartées

### Écartées pour expérience excessive

- Product Owner / Business Analyst Finance F/H, INOCO : plus de 5 ans exigés, et finance de marché purement fonctionnelle.
- Product Builder, Barrière (Paris 8e, 60 à 70 k€, publiée le 01/11) : 7 ans minimum.

**Déjà vues, non rouvertes** : Data Steward, Storm Group (vue le 02/11).

## Conclusion

Journée calme.
"""

REGISTRE = (
    "entreprise;intitule;decision;vue_le;motif;lien\n"
    "INOCO;Product Manager IA (produits GenAI);retenue;2026-11-10;bon fit;"
    "https://www.welcometothejungle.com/fr/companies/inoco/jobs/pm-ia\n"
    "INOCO;Product Owner / Business Analyst Finance F/H;ecartee;2026-11-10;"
    "plus de 5 ans exiges;" + LIEN + "\n")

PAGE = """<html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
"title":"Product Owner / Business Analyst  FinanceF/H","datePosted":"2026-11-10T07:34:49Z",
"hiringOrganization":{"@type":"Organization","name":"INOCO"},
"experienceRequirements":{"@type":"OccupationalExperienceRequirements","monthsOfExperience":60},
"description":"<p>INOCO accompagne ses clients, grands comptes et start-ups.</p>"}</script>
</head><body><nav>Trouver un job</nav><p>Expérience : &gt; 5 ans</p>
<h2>Vos missions au quotidien</h2>
<p>INOCO accompagne ses clients, grands comptes et start-ups.</p>
<h2>Ce que l'on cherche</h2>
<p>Vous avez une expérience significative (&gt; 3-5 ans d'expérience en CDI) en tant que
Product Owner ou de Business Analyst /MOA.</p>
<p>Idéalement, vous avez déjà travaillé dans le secteur Finance.</p>
</body></html>"""


class Reponse:
    text = PAGE

    def raise_for_status(self):
        pass


class ConfigTest(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"


class RattrapageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dossier = Path(tempfile.mkdtemp(prefix="awen-rattrapage-"))
        jour = cls.dossier / "Veille quotidienne" / "2026-11-10"
        jour.mkdir(parents=True)
        (jour / "Compte rendu.md").write_text(COMPTE_RENDU, encoding="utf-8")
        (cls.dossier / "Offres vues.csv").write_text(REGISTRE, encoding="utf-8")
        ConfigTest.JOB_SEARCH_DIR = str(cls.dossier)
        ConfigTest.RATTRAPAGE_FICHIER = str(cls.dossier / "offres-rattrapees.md")
        cls.app = create_app(ConfigTest)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dossier, ignore_errors=True)

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        OffreRattrapee.query.delete()
        CoverLetter.query.delete()
        db.session.commit()
        p = mock.patch.object(rattrapage.requests, "get", return_value=Reponse())
        self.get = p.start()
        self.addCleanup(p.stop)
        self.client = self.app.test_client()

    # --- lire les lignes ------------------------------------------------------

    def test_analyse_ligne(self):
        p = rattrapage.analyse_ligne(
            "- Product Owner / Business Analyst Finance F/H, INOCO : plus de 5 ans exigés.")
        self.assertEqual((p["intitule"], p["entreprise"]),
                         ("Product Owner / Business Analyst Finance F/H", "INOCO"))
        self.assertEqual(p["motif"], "plus de 5 ans exigés.")
        # Les détails entre parenthèses ne collent ni à l'intitulé ni à l'entreprise.
        p = rattrapage.analyse_ligne(
            "- Product Builder, Barrière (Paris 8e, 60 à 70 k€, publiée le 01/11) : 7 ans minimum.")
        self.assertEqual((p["intitule"], p["entreprise"]), ("Product Builder", "Barrière"))
        # Un intitulé à virgules : l'entreprise suit la dernière.
        p = rattrapage.analyse_ligne(
            "- Product Owner, Conduite du changement, Thales : 8 ans.")
        self.assertEqual((p["intitule"], p["entreprise"]),
                         ("Product Owner, Conduite du changement", "Thales"))

    def test_blocs_ecartees(self):
        blocs = rattrapage.blocs_ecartees(
            "### Écartées pour expérience\n\n- A, B : x\n- C, D : y\n\n"
            "**Déjà vues, non rouvertes** : E, F (vue le 02/11).")
        self.assertEqual([b["kind"] for b in blocs], ["md", "liste", "md"])
        self.assertEqual([i["entreprise"] for i in blocs[1]["offres"]], ["B", "D"])

    def test_lien_dans_le_registre(self):
        self.assertEqual(rattrapage.registre_lien(
            "INOCO", "Product Owner / Business Analyst Finance F/H"), LIEN)
        self.assertEqual(rattrapage.registre_lien("Inconnue", "Product Owner"), "")

    def test_l_annonce_garde_le_profil_recherche(self):
        """Le JSON-LD de Welcome to the Jungle ne contient pas « Ce que l'on
        cherche » : c'est pourtant là que se lit l'expérience demandée."""
        texte = rattrapage.extraire(PAGE, LIEN)
        self.assertIn("Intitulé : Product Owner", texte)
        self.assertIn("Entreprise : INOCO", texte)
        self.assertIn("> 3-5 ans", texte)
        self.assertIn("Idéalement", texte)
        self.assertNotIn("Trouver un job", texte)        # la navigation reste dehors

    # --- le geste -------------------------------------------------------------

    def _rattraper(self):
        return self.client.post("/jobs/rattraper", data={
            "rapport": "2026-11-10",
            "ligne": "Product Owner / Business Analyst Finance F/H, INOCO : "
                     "plus de 5 ans exigés, et finance de marché purement fonctionnelle."})

    def test_rattraper_une_offre(self):
        r = self._rattraper()
        self.assertEqual(r.status_code, 302)
        o = OffreRattrapee.query.one()
        self.assertEqual((o.entreprise, o.url), ("INOCO", LIEN))
        self.assertIn("> 3-5 ans", o.texte)
        # Deux fois la même : pas de doublon.
        self._rattraper()
        self.assertEqual(OffreRattrapee.query.count(), 1)

        # La page Jobs la montre en tête, et la ligne écartée le dit.
        page = self.client.get("/jobs/?jour=2026-11-10").get_data(as_text=True)
        self.assertIn('id="rattrapees"', page)
        self.assertIn("Rattrapée, à postuler", page)
        self.assertIn("/jobs/lettres?offre=rattrapee", page)
        self.assertEqual(page.count(">Rattraper</button>"), 1)    # reste Barrière

        # Le formulaire de lettre la propose, avec l'annonce lue sur sa page.
        offre = next(x for x in lettres.offres_recentes() if x["ref"] == rattrapage.ref(o))
        self.assertTrue(offre["label"].startswith("Rattrapée"))
        self.assertIn("> 3-5 ans", offre["texte"])

        # Et la veille la retrouvera, rapatriée par sync-jobs.ps1.
        export = Path(ConfigTest.RATTRAPAGE_FICHIER).read_text(encoding="utf-8")
        self.assertIn("INOCO | Product Owner / Business Analyst Finance F/H", export)
        self.assertIn("plus de 5 ans exigés", export)

    def test_annonce_illisible(self):
        """Un site fermé ne bloque rien : la lettre se demande avec l'annonce
        collée à la main."""
        self.get.side_effect = OSError("refusé")
        self._rattraper()
        o = OffreRattrapee.query.one()
        self.assertEqual(o.texte, "")
        self.assertIn("Lien : " + LIEN, rattrapage.texte_lettre(o))
        page = self.client.get("/jobs/?jour=2026-11-10").get_data(as_text=True)
        self.assertIn("colle-la dans le formulaire de la lettre", page)

    def test_annuler(self):
        self._rattraper()
        o = OffreRattrapee.query.one()
        self.client.post("/jobs/rattrapees/{}/annuler".format(o.id))
        self.assertEqual(OffreRattrapee.query.count(), 0)
        export = Path(ConfigTest.RATTRAPAGE_FICHIER).read_text(encoding="utf-8")
        self.assertNotIn("INOCO |", export)


if __name__ == "__main__":
    unittest.main()
