"""Les lettres de motivation écrites avec Claude, sans appeler Claude.

    python -m unittest tests.test_lettres

Le client Anthropic est remplacé par un faux qui enregistre ce qu'on lui
envoie et répond ce que le test lui dicte : on vérifie la requête (modèle,
repli, sortie structurée, cache, contexte) et ce que l'app fait de la
réponse, jusqu'au PDF et aux leçons. La génération, qui tourne en
arrière-plan dans l'app, est ici exécutée sur place.
"""
import json
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import create_app
from app.config import Config
from app.models import CoverLetter, LetterLesson, db
from app.services import lettres

VRAI_CLIENT = lettres._client

FICHE = """# Fiche profil : Samuel Scalbert

### Les histoires à raconter
- INRIA : suite de trois logiciels SOFTware-Viz/Hub/Sync, du cadrage à la mise en production.

### Les formulations à corriger
- Ne pas écrire « passionné de data ».
"""

CV = """<html><head><style>body{color:red}</style></head><body>
<h1>Samuel Scalbert</h1><p>Product Owner technique</p>
<ul><li>INRIA &amp; Software Heritage</li><li>Python, SQL</li></ul></body></html>"""

INSTRUCTIONS = """# Instructions

### 7. Le CV
Rien ici.

### 8. Lettres de motivation : uniquement sur demande
- Chaque lettre contient un élément concret de l'entreprise, une histoire vérifiée, et le traitement explicite de la friction principale.

### 9. Écriture du compte rendu
Rien ici non plus.
"""

GABARIT = """# Modèle de lettre

---

Samuel Scalbert
56 boulevard de Port-Royal 75005
0600000000 - adresse@exemple.fr

[Date] - Paris
"""

ENVOYEE = """# Exemple SA, Data Analyst

- Date : 01/10/2026

---

Samuel Scalbert

Madame, Monsieur,

Très enthousiaste à l'idée de rejoindre Exemple SA en tant que Data Analyst.
"""


class ConfigTest(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    ANTHROPIC_API_KEY = "cle-de-test"
    LETTRE_MODEL = "claude-opus-5-5"
    LETTRE_EFFORT = "high"


def reponse(data, stop="end_turn"):
    """Ce que renvoie client.beta.messages.create : une réflexion, puis le JSON."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""),
                 SimpleNamespace(type="text", text=json.dumps(data))],
        stop_reason=stop, model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=1200, output_tokens=900,
                              cache_read_input_tokens=9000,
                              cache_creation_input_tokens=0))


LETTRE = {
    "entreprise": "Yavin",
    "poste": "Product Owner Core",
    "destinataire": ["À l'attention de l'équipe recrutement", "Yavin", "Paris"],
    "objet": "Candidature au poste de Product Owner Core",
    "salutation": "Madame, Monsieur,",
    "paragraphes": [
        "Très enthousiaste à l'idée de rejoindre Yavin — en tant que Product Owner Core, je veux mettre à profit mon double profil.",
        "Ce qui m'attire chez Yavin, c'est le paiement simple pour les commerçants.",
        "À l'INRIA, j'ai porté la suite SOFTware-Viz/Hub/Sync du cadrage à la production.",
        "Je n'ai pas encore travaillé dans le paiement : j'apprendrai vite le domaine.",
        "Je vous remercie de l'attention portée à ma candidature.",
    ],
    "notes": "Élément concret : le paiement des commerçants (offre).\nÀ vérifier : la ville.",
}


class FauxClaude:
    def __init__(self):
        self.appels = []
        self.reponses = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.appels.append(kwargs)
        return self.reponses.pop(0)


class LettresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dossier = Path(tempfile.mkdtemp(prefix="awen-lettres-"))
        (cls.dossier / "Lettres de motivation").mkdir()
        (cls.dossier / "Fiche profil - Samuel Scalbert.md").write_text(FICHE, encoding="utf-8")
        (cls.dossier / "_CV ATS (source modifiable).html").write_text(CV, encoding="utf-8")
        (cls.dossier / "_Instructions veille PO (tache quotidienne).md").write_text(
            INSTRUCTIONS, encoding="utf-8")
        (cls.dossier / "Lettres de motivation" / "_Modele de lettre (template).md").write_text(
            GABARIT, encoding="utf-8")
        (cls.dossier / "Lettres de motivation" / "Exemple SA - Data Analyst.md").write_text(
            ENVOYEE, encoding="utf-8")
        ConfigTest.JOB_SEARCH_DIR = str(cls.dossier)
        cls.app = create_app(ConfigTest)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dossier, ignore_errors=True)

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        LetterLesson.query.delete()
        CoverLetter.query.delete()
        db.session.commit()
        self.claude = FauxClaude()
        self.addCleanup(self.ctx.pop)
        for nom, faux in (("_client", lambda: self.claude),
                          ("lancer", lambda f, i: f(i))):
            p = mock.patch.object(lettres, nom, faux)
            p.start()
            self.addCleanup(p.stop)
        self.client = self.app.test_client()

    def _ecrire(self, priorites="Citer SOFTware-Viz.", data=LETTRE):
        self.claude.reponses.append(reponse(data))
        r = self.client.post("/jobs/lettres/nouvelle", data={
            "offre": "Yavin recrute un Product Owner Core pour son terminal de paiement.",
            "priorites": priorites})
        self.assertEqual(r.status_code, 302)
        lettre_id = int(r.headers["Location"].rstrip("/").rsplit("/", 1)[-1])
        return db.session.get(CoverLetter, lettre_id)

    # --- la requête -----------------------------------------------------------

    def test_la_requete_suit_les_regles_de_l_api(self):
        l = self._ecrire()
        self.assertEqual(l.etat, "prete", l.erreur)
        appel = self.claude.appels[0]
        self.assertEqual(appel["model"], "claude-opus-5-5")
        self.assertEqual(appel["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(appel["fallbacks"], "default")
        self.assertEqual(appel["output_config"]["effort"], "high")
        fmt = appel["output_config"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertFalse(fmt["schema"]["additionalProperties"])
        self.assertNotIn("thinking", appel)       # toujours actif sur Opus 5.5
        systeme = appel["system"][0]
        self.assertEqual(systeme["cache_control"], {"type": "ephemeral"})

    def test_le_contexte_vient_du_projet(self):
        self._ecrire()
        systeme = self.claude.appels[0]["system"][0]["text"]
        self.assertIn("SOFTware-Viz/Hub/Sync", systeme)        # fiche profil
        self.assertIn("passionné de data", systeme)            # formulations à corriger
        self.assertIn("INRIA & Software Heritage", systeme)    # CV, balises retirées
        self.assertNotIn("color:red", systeme)
        self.assertIn("élément concret de l'entreprise", systeme)   # section 8
        self.assertNotIn("Écriture du compte rendu", systeme)       # pas la 9
        self.assertIn("Très enthousiaste à l'idée de rejoindre Exemple SA", systeme)
        demande = self.claude.appels[0]["messages"][0]["content"]
        self.assertIn("terminal de paiement", demande)
        self.assertIn("Citer SOFTware-Viz.", demande)

    def test_la_reponse_remplit_la_lettre(self):
        l = self._ecrire()
        self.assertEqual(l.entreprise, "Yavin")
        self.assertEqual(l.destinataire.splitlines()[1], "Yavin")
        self.assertEqual(len(l.corps.split("\n\n")), 5)
        self.assertNotIn("—", l.corps)                    # tiret long retiré
        self.assertIn("Yavin, en tant que", l.corps)
        self.assertTrue(l.expediteur.startswith("Samuel Scalbert"))
        self.assertRegex(l.date_ligne, r"^\d\d/\d\d/\d{4} - Paris$")
        self.assertEqual(json.loads(l.brouillon)["corps"], l.corps)
        self.assertEqual((l.jetons_entree, l.jetons_sortie), (10200, 900))

    # --- les échecs -------------------------------------------------------------

    def test_sans_cle(self):
        self.app.config["ANTHROPIC_API_KEY"] = ""
        try:
            # Le vrai _client, cette fois : c'est lui qui refuse.
            with mock.patch.object(lettres, "_client", VRAI_CLIENT):
                l = self._ecrire_sans_reponse()
                page = self.client.get("/jobs/lettres").get_data(as_text=True)
        finally:
            self.app.config["ANTHROPIC_API_KEY"] = "cle-de-test"
        self.assertEqual(l.etat, "erreur")
        self.assertIn("ANTHROPIC_API_KEY", l.erreur)
        self.assertIn("ANTHROPIC_API_KEY", page)          # prévenu avant de cliquer

    def _ecrire_sans_reponse(self):
        r = self.client.post("/jobs/lettres/nouvelle", data={"offre": "Une offre."})
        return db.session.get(CoverLetter,
                              int(r.headers["Location"].rsplit("/", 1)[-1]))

    def test_refus(self):
        self.claude.reponses.append(reponse({}, stop="refusal"))
        l = self._ecrire_sans_reponse()
        self.assertEqual(l.etat, "erreur")
        self.assertIn("refusé", l.erreur)

    def test_fiche_profil_absente(self):
        fiche = self.dossier / "Fiche profil - Samuel Scalbert.md"
        fiche.rename(fiche.with_suffix(".bak"))
        try:
            l = self._ecrire_sans_reponse()
        finally:
            fiche.with_suffix(".bak").rename(fiche)
        self.assertEqual(l.etat, "erreur")
        self.assertIn("fiche profil", l.erreur)
        self.assertEqual(self.claude.appels, [])      # rien n'est parti

    def test_generation_perdue_au_redemarrage(self):
        recente = CoverLetter(etat="generation")
        perdue = CoverLetter(etat="generation",
                             updated_at=datetime.now() - timedelta(minutes=30))
        db.session.add_all([recente, perdue])
        db.session.commit()
        etat = self.client.get("/jobs/lettres/{}/etat".format(perdue.id)).get_json()
        self.assertEqual(etat["etat"], "erreur")
        self.assertIn("relance", etat["erreur"])
        etat = self.client.get("/jobs/lettres/{}/etat".format(recente.id)).get_json()
        self.assertEqual(etat["etat"], "generation")

    # --- l'éditeur et le PDF -----------------------------------------------------

    def test_pages(self):
        l = self._ecrire()
        for url in ("/jobs/lettres", "/jobs/lettres/{}".format(l.id),
                    "/jobs/lettres/{}/etat".format(l.id)):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        page = self.client.get("/jobs/lettres/{}".format(l.id)).get_data(as_text=True)
        self.assertIn("Générer et télécharger le PDF", page)
        self.assertIn("Élément concret", page)

    def test_enregistrer(self):
        l = self._ecrire()
        r = self.client.post("/jobs/lettres/{}/enregistrer".format(l.id),
                             json={"objet": "Candidature : Product Owner Core"})
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(db.session.get(CoverLetter, l.id).objet,
                         "Candidature : Product Owner Core")

    def _champs(self, l, **changes):
        d = {k: getattr(l, k) for k in ("expediteur", "date_ligne", "destinataire",
                                        "objet", "salutation", "corps", "entreprise")}
        d.update(changes)
        return d

    def test_pdf_une_page_sans_metadonnee(self):
        l = self._ecrire()
        r = self.client.post("/jobs/lettres/{}/pdf".format(l.id), data=self._champs(l))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/pdf")
        self.assertIn("Yavin - Lettre de motivation.pdf",
                      r.headers["Content-Disposition"])
        pdf = r.data
        self.assertEqual(len(re.findall(rb"/Type\s*/Page\b", pdf)), 1)
        for mouchard in (b"ReportLab", b"anonymous", b"CreationDate", b"ModDate",
                         b"/Producer", b"/Author"):
            self.assertNotIn(mouchard, pdf)
        self.assertIsNotNone(db.session.get(CoverLetter, l.id).exportee_le)

        # Les signatures sont effacées sans décaler le fichier : chaque entrée
        # de la table xref pointe toujours sur son objet.
        xref = int(re.search(rb"startxref\s+(\d+)", pdf).group(1))
        self.assertTrue(pdf[xref:].startswith(b"xref"))
        lignes = pdf[xref:].split(b"\n")
        for numero, ligne in enumerate(lignes[3:3 + int(lignes[1].split()[1]) - 1], 1):
            position = int(ligne.split()[0])
            self.assertTrue(pdf[position:].startswith(b"%d 0 obj" % numero), numero)

    def test_trop_long(self):
        l = self._ecrire()
        long = "\n\n".join(["Un paragraphe bien rempli " * 30] * 6)
        r = self.client.post("/jobs/lettres/{}/pdf".format(l.id),
                             data=self._champs(l, corps=long))
        self.assertEqual(r.status_code, 422)
        self.assertIn("dépasse une page", r.get_json()["erreur"])
        # La correction est gardée même si le PDF n'a pas pu se faire.
        self.assertEqual(db.session.get(CoverLetter, l.id).corps, long)

    # --- apprendre ---------------------------------------------------------------

    def test_les_corrections_deviennent_des_lecons(self):
        l = self._ecrire()
        corrige = l.corps.replace("j'apprendrai vite le domaine",
                                  "j'ai lu leur documentation d'API et monté un prototype")
        corrige = corrige.replace("Très enthousiaste à l'idée de rejoindre Yavin, en tant que",
                                  "Je candidate chez Yavin comme")
        self.claude.reponses.append(reponse({"lecons": [
            "Remplace les promesses d'apprentissage par une preuve déjà faite.",
            "Ouvre sans formule d'enthousiasme — entre directement dans le sujet."]}))
        r = self.client.post("/jobs/lettres/{}/pdf".format(l.id),
                             data=self._champs(l, corps=corrige))
        self.assertEqual(r.status_code, 200)
        lecons = LetterLesson.query.order_by(LetterLesson.id).all()
        self.assertEqual(len(lecons), 2)
        self.assertNotIn("—", lecons[1].texte)
        appel = self.claude.appels[1]
        self.assertEqual(appel["output_config"]["effort"], "medium")
        self.assertIn("monté un prototype", appel["messages"][0]["content"])

        # Le même export une seconde fois ne repaie pas l'analyse.
        self.client.post("/jobs/lettres/{}/pdf".format(l.id),
                         data=self._champs(l, corps=corrige))
        self.assertEqual(len(self.claude.appels), 2)

        # La lettre suivante reçoit les leçons et la correction elle-même.
        self._ecrire()
        demande = self.claude.appels[2]["messages"][0]["content"]
        self.assertIn("Remplace les promesses d'apprentissage", demande)
        self.assertIn("<envoye_par_samuel>", demande)
        self.assertIn("monté un prototype", demande)

    def test_une_coquille_ne_coute_pas_d_analyse(self):
        l = self._ecrire()
        r = self.client.post("/jobs/lettres/{}/pdf".format(l.id),
                             data=self._champs(l, corps=l.corps.replace("vite", "vite.")))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.claude.appels), 1)

    def test_gerer_les_lecons(self):
        lecon = LetterLesson(texte="Une règle.")
        db.session.add(lecon)
        db.session.commit()
        self.client.post("/jobs/lettres/lecons/{}".format(lecon.id),
                         data={"action": "basculer"})
        self.assertFalse(db.session.get(LetterLesson, lecon.id).active)
        self.client.post("/jobs/lettres/lecons/{}".format(lecon.id),
                         data={"action": "supprimer"})
        self.assertIsNone(db.session.get(LetterLesson, lecon.id))

    def test_regenerer_garde_l_ancienne(self):
        l = self._ecrire()
        self.claude.reponses.append(reponse(dict(LETTRE, objet="Autre objet")))
        r = self.client.post("/jobs/lettres/{}/regenerer".format(l.id),
                             data={"priorites": "Parler du télétravail."})
        nouvelle = db.session.get(CoverLetter,
                                  int(r.headers["Location"].rsplit("/", 1)[-1]))
        self.assertNotEqual(nouvelle.id, l.id)
        self.assertEqual(nouvelle.objet, "Autre objet")
        self.assertEqual(nouvelle.priorites, "Parler du télétravail.")
        self.assertIsNotNone(db.session.get(CoverLetter, l.id))


if __name__ == "__main__":
    unittest.main()
