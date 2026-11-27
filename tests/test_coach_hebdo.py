"""Le bilan du dimanche : la semaine relue, le dossier, le tri des réponses.

    python -m unittest tests.test_coach_hebdo

Claude n'est jamais appelé : sa réponse est simulée.
"""
import json
import unittest
from datetime import date, datetime
from unittest import mock

from app import create_app
from app.config import Config
from app.models import (CoachDecision, ExerciseNote, ExerciseSet,
                        ProgramExercise, WeeklyBrief, Workout, db)
from app.services import coach, coach_hebdo
from app.services.charges import shown

DIMANCHE = date(2026, 11, 22)
LUNDI = date(2026, 11, 16)


class ConfigTest(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SAMSUNG_CALENDAR_ICS_URL = ""
    JOB_SEARCH_DIR = ""


class CoachHebdoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(ConfigTest)

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        for m in (WeeklyBrief, CoachDecision, ExerciseNote, ExerciseSet, Workout):
            m.query.delete()
        db.session.commit()
        self.pe = (ProgramExercise.query
                   .filter(ProgramExercise.active.is_(True),
                           ProgramExercise.block == "force",
                           ProgramExercise.weight_kg > 0,
                           ProgramExercise.increment_kg > 0)
                   .order_by(ProgramExercise.id).first())
        self.poids = self.pe.weight_kg
        self.addCleanup(self._remet_charge)
        # Une séance le lundi de la semaine relue, avec un commentaire.
        w = Workout(date=datetime(2026, 11, 16, 18, 30), focus="Push",
                    completed=True)
        db.session.add(w)
        db.session.flush()
        for i, reps in enumerate((12, 11, 10), 1):
            db.session.add(ExerciseSet(
                workout_id=w.id, program_exercise_id=self.pe.id,
                exercise=self.pe.name, set_number=i, reps=reps,
                weight_kg=self.pe.weight_kg, rir=2))
        db.session.add(ExerciseNote(workout_id=w.id,
                                    program_exercise_id=self.pe.id,
                                    text="on monte à 4 sets"))
        db.session.commit()

    def _remet_charge(self):
        self.pe.weight_kg = self.poids
        db.session.commit()

    def _reponse(self, **kw):
        data = {
            "bilan": "Une séance sur trois.", "suivi": "",
            "prochaine_seance": ["Commence par les jambes.", " ", "Pèse-toi."],
            "charges": [], "cycle": {"decharge": False, "pourquoi": "1re semaine."},
            "question": "Mercredi, absent ou séance sautée ?",
        }
        data.update(kw)
        return data

    # -- la semaine relue ---------------------------------------------------

    def test_semaine_relue(self):
        self.assertEqual(coach_hebdo.semaine_relue(DIMANCHE), LUNDI)
        # Rattrapage du lundi matin : la semaine qui vient de finir.
        self.assertEqual(coach_hebdo.semaine_relue(date(2026, 11, 23)), LUNDI)
        self.assertEqual(coach_hebdo.semaine_relue(date(2026, 11, 18)),
                         date(2026, 11, 9))

    # -- le dossier ---------------------------------------------------------

    def test_dossier_complet_et_serialisable(self):
        d = coach_hebdo.dossier(LUNDI, DIMANCHE)
        json.dumps(d, ensure_ascii=False)
        self.assertEqual(len(d["seances"]), 1)
        exo = d["seances"][0]["exercices"][0]
        self.assertEqual(exo["commentaire"], "on monte à 4 sets")
        self.assertEqual([s["reps"] for s in exo["series"]], [12, 11, 10])
        self.assertEqual(len(d["prochaines_seances"]), 3)
        self.assertEqual(d["prochaines_seances"][0]["date"], "2026-11-23")
        self.assertEqual(len(d["tendance"]), coach_hebdo.SEMAINES)
        self.assertIsNone(d["bilan_precedent"])
        # Mercredi et vendredi sans séance.
        self.assertEqual([m["jour"] for m in d["seances_manquees"]],
                         ["vendredi", "mercredi"])

    # -- la réponse de Claude ----------------------------------------------

    def test_ne_garde_que_les_charges_applicables(self):
        plus_dur = shown(coach._harder(self.pe), self.pe)
        plyo = ProgramExercise.query.filter_by(block="plyo").first()
        charges = [
            {"exercice_id": self.pe.id, "charge": plus_dur, "raison": "12 partout."},
            {"exercice_id": self.pe.id, "charge": plus_dur, "raison": "doublon"},
            {"exercice_id": 99999, "charge": 40, "raison": "inconnu"},
            {"exercice_id": plyo.id, "charge": 20, "raison": "plyo"},
        ]
        autre = (ProgramExercise.query
                 .filter(ProgramExercise.active.is_(True),
                         ProgramExercise.block == "force",
                         ProgramExercise.weight_kg > 0,
                         ProgramExercise.id != self.pe.id).first())
        # Trois fois la charge : une erreur de lecture, pas un ajustement.
        charges.append({"exercice_id": autre.id,
                        "charge": shown(autre.weight_kg, autre) * 3,
                        "raison": "trop"})
        with mock.patch.object(coach_hebdo, "_demander",
                               return_value=self._reponse(charges=charges)):
            b, cree = coach_hebdo.generer(DIMANCHE)
        self.assertTrue(cree)
        self.assertEqual(b.source, "claude")
        self.assertEqual(b.semaine, LUNDI)
        gardees = b.contenu["charges"]
        self.assertEqual(len(gardees), 1)
        self.assertAlmostEqual(gardees[0]["charge_kg"], coach._harder(self.pe))
        # Les consignes vides tombent.
        self.assertEqual(b.contenu["prochaine_seance"],
                         ["Commence par les jambes.", "Pèse-toi."])
        self.assertEqual(b.question, "Mercredi, absent ou séance sautée ?")

    def test_repli_sur_les_regles_si_claude_echoue(self):
        with mock.patch.object(coach_hebdo, "_demander",
                               side_effect=coach_hebdo.CoachHebdoErreur("hors ligne")):
            b, _ = coach_hebdo.generer(DIMANCHE)
        self.assertEqual(b.source, "regles")
        self.assertEqual(b.erreur, "hors ligne")
        self.assertIn("1 séance sur 3", b.contenu["bilan"])

    def test_un_bon_bilan_n_est_pas_ecrase(self):
        with mock.patch.object(coach_hebdo, "_demander",
                               return_value=self._reponse()):
            premier, _ = coach_hebdo.generer(DIMANCHE)
        with mock.patch.object(coach_hebdo, "_demander") as appel:
            b, cree = coach_hebdo.generer(DIMANCHE)
        self.assertFalse(cree)
        appel.assert_not_called()
        with mock.patch.object(coach_hebdo, "_demander",
                               side_effect=coach_hebdo.CoachHebdoErreur("x")):
            with self.assertRaises(coach_hebdo.CoachHebdoErreur):
                coach_hebdo.generer(DIMANCHE, refaire=True)
        self.assertEqual(WeeklyBrief.query.one().source, "claude")

    def test_le_bilan_suivant_relit_le_precedent(self):
        plus_dur = shown(coach._harder(self.pe), self.pe)
        reponse = self._reponse(charges=[{"exercice_id": self.pe.id,
                                          "charge": plus_dur, "raison": "ok"}])
        with mock.patch.object(coach_hebdo, "_demander", return_value=reponse):
            b, _ = coach_hebdo.generer(DIMANCHE)
        coach_hebdo.repondre(b, "  absent, déplacement  ")
        coach.apply_advice(self.pe.id, b.contenu["charges"][0]["charge_kg"], "test")
        precedent = coach_hebdo.dossier(date(2026, 11, 23), date(2026, 11, 29))["bilan_precedent"]
        self.assertEqual(precedent["reponse"], "absent, déplacement")
        self.assertTrue(precedent["charges"][0]["appliquee"])

    # -- la règle de stagnation du coach -------------------------------------

    def _stagnation(self, series):
        from types import SimpleNamespace
        lo, hi = self.pe.rep_min, self.pe.rep_max
        hist = [{"date": date(2026, 11, d), "weight": self.pe.weight_kg,
                 "reps": [min(max(r, lo), hi)] * 4, "rir": None,
                 "sets": [SimpleNamespace(reps=min(max(r, lo), hi))] * 4}
                for d, r in zip((2, 4, 6), series)]
        advice = []
        coach._exercise_advice(self.pe, hist, advice)
        return [a for a in advice if "stagne" in a["title"]]

    def test_meme_charge_et_reps_qui_montent_n_est_pas_un_plateau(self):
        lo, hi = self.pe.rep_min, self.pe.rep_max
        self.assertEqual(self._stagnation([lo, lo + 1, hi]), [])

    def test_meme_charge_et_memes_reps_est_un_plateau(self):
        lo = self.pe.rep_min
        self.assertEqual(len(self._stagnation([lo + 1, lo + 1, lo + 1])), 1)

    # -- les pages ----------------------------------------------------------

    def test_pages(self):
        with mock.patch.object(coach_hebdo, "_demander",
                               return_value=self._reponse()):
            b, _ = coach_hebdo.generer(DIMANCHE)
        client = self.app.test_client()
        page = client.get("/coach/").get_data(as_text=True)
        self.assertIn("Bilan du dimanche", page)
        self.assertIn("Commence par les jambes.", page)
        self.assertIn("Mercredi, absent ou séance sautée ?", page)
        accueil = client.get("/").get_data(as_text=True)
        self.assertIn("Lire le bilan", accueil)
        self.assertIn("Une question t", accueil)

        r = client.post(f"/coach/bilan/{b.id}/reponse",
                        data={"reponse": "Absent."})
        self.assertEqual(r.status_code, 302)
        db.session.refresh(b)
        self.assertEqual(b.reponse, "Absent.")
        self.assertNotIn("Une question t",
                         client.get("/").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
