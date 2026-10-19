"""La salle : le choix des séances, les crans, la dernière fois, le rappel.

    python -m unittest tests.test_seance

Base en mémoire, programme de départ du seed, puis les corrections du
19/10/2026 telles qu'elles s'appliquent au démarrage.
"""
import json
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta
from html import unescape
from pathlib import Path
from unittest import mock

from app import create_app
from app.config import Config
from app.models import (DataMigration, ExerciseNote, ExerciseSet,
                        ProgramExercise, Workout, db)
from app.seed import gym_in_pounds
from app.services import agenda_google, charges, rappels
from app.services.progression import SEANCES, apply_progression, rotation


class ConfigTest(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SAMSUNG_CALENDAR_ICS_URL = ""
    JOB_SEARCH_DIR = ""
    RAPPEL_SEANCE_HEURE = "20:30"


def lb(v):
    return charges.to_kg(v, "lb")


class SalleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(ConfigTest)

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        ExerciseNote.query.delete()
        ExerciseSet.query.delete()
        Workout.query.delete()
        db.session.commit()
        self.client = self.app.test_client()

    def pe(self, slug, stype=None):
        q = ProgramExercise.query.filter_by(slug=slug, active=True)
        if stype:
            q = q.filter_by(session_type=stype)
        return q.first()

    def seance(self, focus, jour, completed=True, sets=(), note=None):
        """Une séance passée : sets = [(slug, reps, charge en kg)]."""
        w = Workout(focus=focus, date=jour, completed=completed)
        db.session.add(w)
        db.session.flush()
        for i, (slug, reps, kg) in enumerate(sets, 1):
            pe = self.pe(slug)
            db.session.add(ExerciseSet(workout_id=w.id, program_exercise_id=pe.id,
                                       exercise=pe.name, set_number=i,
                                       reps=reps, weight_kg=kg))
        if note:
            slug, texte = note
            db.session.add(ExerciseNote(workout_id=w.id,
                                        program_exercise_id=self.pe(slug).id,
                                        text=texte))
        db.session.commit()
        return w

    def cartes(self, html):
        """Les données de chaque exercice, telles que les lit le script."""
        return {d["name"]: d for d in
                (json.loads(unescape(m)) for m in re.findall(r'data-card="([^"]+)"', html))}

    # --- les corrections du 19/10 --------------------------------------------

    def test_retours_appliques(self):
        self.assertIsNone(self.pe("pompes", "legs"))
        self.assertEqual(self.pe("triceps-poulie").sets, 4)
        plyo = ProgramExercise.query.filter_by(block="plyo", active=True).all()
        self.assertTrue(plyo)
        self.assertEqual({p.session_type for p in plyo}, {"plyo"})
        slugs = [p.slug for p in plyo]
        self.assertEqual(len(slugs), len(set(slugs)))       # corde une seule fois
        self.assertEqual(sorted(p.position for p in plyo), list(range(1, len(plyo) + 1)))

    def test_salle_en_livres(self):
        for pe in ProgramExercise.query.filter_by(block="force"):
            self.assertEqual((pe.load_unit, charges.step_of(pe)), ("lb", 10), pe.name)
            v = charges.from_kg(pe.weight_kg, "lb")
            self.assertAlmostEqual(v, round(v / 10) * 10, places=2, msg=pe.name)
        tractions = self.pe("tractions")
        self.assertAlmostEqual(tractions.increment_kg, -lb(10), places=3)
        self.assertEqual(self.pe("mollets").increment_kg, 0)

    def test_corrections_jouees_une_fois(self):
        poulie = self.pe("triceps-poulie")
        poulie.load_unit, poulie.load_step = "kg", 2.5
        db.session.commit()
        gym_in_pounds()
        self.assertEqual(self.pe("triceps-poulie").load_unit, "kg")
        self.assertIsNotNone(db.session.get(DataMigration, "2026-10-19-salle-en-livres"))
        charges.set_machine(poulie, "lb", 10)
        db.session.commit()

    # --- les charges ---------------------------------------------------------

    def test_charges(self):
        pe = self.pe("chest-press")
        # En kilos à l'écran, sur les crans d'une pile graduée en livres.
        self.assertEqual(charges.label(lb(70), pe), "31,8 kg")
        self.assertEqual(charges.label(lb(80), pe), "36,3 kg")
        self.assertEqual(charges.label(32, pe), "32 kg")             # saisie d'avant
        self.assertEqual(charges.snap(34.5, pe), lb(80))              # 76 lb → 80
        self.assertEqual(charges.snap(lb(75), pe), lb(70))            # demi-cran : en bas
        # Ce qu'on lit à l'écran retombe sur le cran exact ; le reste est voulu.
        self.assertEqual(charges.from_display(31.8, pe), lb(70))
        self.assertEqual(charges.from_display(33, pe), 33)
        self.assertEqual(charges.machine_label(pe), "pile en livres, crans de 10 lb (4,5 kg)")
        self.assertEqual(charges.increment_steps(self.pe("tractions")), -1)
        self.assertEqual(charges.number(32.5), "32,5")

    def test_machine_en_kilos(self):
        pe = self.pe("tractions")
        r = self.client.post("/workouts/programme/{}/machine".format(pe.id),
                             data={"load_unit": "kg", "load_step": "2.5"})
        self.assertTrue(r.get_json()["ok"])
        pe = db.session.get(ProgramExercise, pe.id)
        self.assertEqual(pe.increment_kg, -2.5)                     # le signe reste
        self.assertEqual(round(pe.weight_kg / 2.5, 6) % 1, 0)       # sur un cran
        charges.set_machine(pe, "lb", 10)
        db.session.commit()

    # --- l'écran de la salle --------------------------------------------------

    def test_cinq_seances_dans_l_ordre(self):
        html = self.client.get("/workouts/").get_data(as_text=True)
        noms = re.findall(r'class="gym-choice-name">([^<]+)<', html)
        self.assertEqual(noms, SEANCES)
        self.assertEqual(SEANCES, ["Push", "Pull", "Legs", "Plyo", "Reprise"])

    def test_lire_ne_cree_rien(self):
        self.assertEqual(self.client.get("/workouts/session").status_code, 302)
        self.assertEqual(Workout.query.count(), 0)

    def test_choisir_legs(self):
        r = self.client.post("/workouts/commencer/legs")
        self.assertEqual(r.status_code, 302)
        w = Workout.query.one()
        self.assertEqual((w.focus, w.completed), ("Legs", False))
        html = self.client.get("/workouts/session").get_data(as_text=True)
        self.assertIn("Leg extension", html)
        self.assertNotIn("Pompes", html)

    def test_une_seance_vide_d_hier_ne_bloque_plus(self):
        hier = datetime.now() - timedelta(days=1)
        self.seance("Pull", hier, completed=False)
        self.client.post("/workouts/commencer/push")
        self.assertEqual([w.focus for w in Workout.query.all()], ["Push"])

    def test_une_seance_oubliee_est_terminee(self):
        hier = datetime.now() - timedelta(days=1)
        old = self.seance("Push", hier, completed=False,
                          sets=[("developpe-incline", 12, lb(70))] * 4)
        avant = self.pe("developpe-incline").weight_kg
        r = self.client.post("/workouts/commencer/legs", follow_redirects=True)
        self.assertIn("terminée", r.get_data(as_text=True))
        self.assertTrue(db.session.get(Workout, old.id).completed)
        self.assertEqual(self.pe("developpe-incline").weight_kg, lb(80))  # progression
        self.assertNotEqual(avant, lb(80))

    def test_changer_de_seance_en_cours_demande_confirmation(self):
        self.client.post("/workouts/commencer/push")
        w = Workout.query.one()
        pe = self.pe("chest-press")
        self.client.post("/workouts/session/{}/log".format(w.id),
                         data={"exercise_id": pe.id, "reps": 10, "weight": "36.3"})
        self.client.post("/workouts/commencer/plyo")
        self.assertEqual(Workout.query.count(), 1)                    # rien n'a bougé
        self.client.post("/workouts/commencer/plyo", data={"confirmer": "1"})
        self.assertEqual(sorted(w.focus for w in Workout.query.all()), ["Plyo", "Push"])
        self.assertTrue(db.session.get(Workout, w.id).completed)

    def test_reprendre_la_meme(self):
        self.client.post("/workouts/commencer/pull")
        self.client.post("/workouts/commencer/pull")
        self.assertEqual(Workout.query.count(), 1)

    # --- la séance ------------------------------------------------------------

    def test_serie_en_kilos(self):
        self.client.post("/workouts/commencer/push")
        w = Workout.query.one()
        pe = self.pe("chest-press")
        j = self.client.post("/workouts/session/{}/log".format(w.id),
                             data={"exercise_id": pe.id, "reps": 10,
                                   "weight": "36.3"}).get_json()
        self.assertEqual(j["weight"], 36.3)
        s = ExerciseSet.query.one()
        self.assertEqual(s.weight_kg, lb(80))           # le cran exact, pas 36,3

    def test_progression_d_un_cran(self):
        pe = self.pe("chest-press")
        w = self.seance("Push", datetime.now(), completed=False,
                        sets=[("chest-press", pe.rep_max, lb(80))] * pe.sets)
        changes = apply_progression(w)
        self.assertEqual(self.pe("chest-press").weight_kg, lb(90))
        self.assertTrue(any(c.endswith("→ 40,8 kg") for c in changes), changes)

    def test_la_derniere_fois(self):
        il_y_a_3_jours = datetime.now() - timedelta(days=3)
        self.seance("Reprise", il_y_a_3_jours - timedelta(days=4),
                    sets=[("leg-curl", 8, lb(90))])
        self.seance("Legs", il_y_a_3_jours,
                    sets=[("leg-curl", 16, 43), ("leg-curl", 15, 43)],
                    note=("leg-curl", "Siège au cran 4"))
        self.client.post("/workouts/commencer/legs")
        html = self.client.get("/workouts/session").get_data(as_text=True)
        carte = self.cartes(html)["Leg curl"]
        self.assertEqual([(p["v"], p["reps"]) for p in carte["prev"]], [(43, 16), (43, 15)])
        self.assertEqual(carte["grid"], "lb")
        self.assertAlmostEqual(carte["stepkg"], 4.5359, places=4)
        self.assertIn("Siège au cran 4", html)
        self.assertIn("Dernière fois le {}".format(il_y_a_3_jours.strftime("%d/%m")), html)

    def test_plyo_seance_a_part(self):
        self.client.post("/workouts/commencer/plyo")
        html = self.client.get("/workouts/session").get_data(as_text=True)
        cartes = self.cartes(html)
        self.assertIn("Box jumps", cartes)
        self.assertEqual(sum(1 for n in cartes if n.startswith("Rebonds")), 1)
        self.assertTrue(all(not c["loaded"] for c in cartes.values()))
        w = Workout.query.one()
        r = self.client.post("/workouts/session/{}/finish".format(w.id),
                             follow_redirects=True).get_data(as_text=True)
        self.assertIn("Séance Plyo terminée", r)
        self.assertNotIn("Progression :", r)

    def test_suggestion_la_plus_ancienne(self):
        now = datetime.now()
        self.seance("Pull", now - timedelta(days=9), sets=[("low-row", 12, lb(90))])
        self.seance("Legs", now - timedelta(days=4), sets=[("squat", 12, lb(150))])
        self.seance("Push", now - timedelta(days=2), sets=[("chest-press", 10, lb(80))])
        # Une séance close sans série ne compte pas comme faite.
        self.seance("Pull", now - timedelta(days=1))
        self.assertEqual(rotation(), ["Pull", "Legs", "Push"])

    # --- le rappel du soir ----------------------------------------------------

    def test_rappels(self):
        lundi = date(2026, 10, 19)
        # Rien de commencé : pas de rappel, même un jour d'entraînement.
        self.assertEqual(rappels.rappels(today=lundi), [])

        # Commencée le matin, pas terminée : rappel le soir, à l'heure réglée.
        w = self.seance("Push", datetime(2026, 10, 19, 10), completed=False,
                        sets=[("chest-press", 10, lb(80))])
        [(moment, titre, texte)] = rappels.rappels(today=lundi)
        self.assertEqual(moment, datetime(2026, 10, 19, 20, 30))
        self.assertIn("termine ta séance Push", titre)
        self.assertIn("1 série notée", texte)

        # Commencée tard : une heure et demie après le début.
        w.date = datetime(2026, 10, 19, 20, 0)
        db.session.commit()
        self.assertEqual(rappels.rappels(today=lundi)[0][0], datetime(2026, 10, 19, 21, 30))

        # Terminée : plus de rappel.
        w.completed = True
        db.session.commit()
        self.assertEqual(rappels.rappels(today=lundi), [])

        # Commencée la veille : ce n'est plus le rappel d'aujourd'hui.
        self.seance("Legs", datetime(2026, 10, 18, 10), completed=False)
        self.assertEqual(rappels.rappels(today=lundi), [])

    def test_flux_ics(self):
        r = self.client.get("/calendar/rappels.ics")
        self.assertEqual(r.mimetype, "text/calendar")
        texte = r.get_data(as_text=True)
        self.assertIn("X-WR-CALNAME:Awen", texte)
        self.assertNotIn("BEGIN:VEVENT", texte)        # rien de commencé

        self.seance("Pull", datetime.combine(date.today(), datetime.min.time())
                    + timedelta(hours=9), completed=False)
        texte = self.client.get("/calendar/rappels.ics").get_data(as_text=True)
        self.assertIn("DTSTART:{}T203000".format(date.today().strftime("%Y%m%d")), texte)
        self.assertIn("BEGIN:VALARM", texte)
        self.assertIn("termine ta séance Pull", texte.replace("\r\n ", ""))

    # --- l'agenda Google ------------------------------------------------------

    def google(self, codes=None):
        """Un faux Google qui note chaque appel ; codes : réponses imposées."""
        appels = []
        codes = list(codes or [])

        class Reponse:
            def __init__(self, code):
                self.status_code = code

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(self.status_code)

        class Faux:
            def post(self, url, json, timeout):
                appels.append(("POST", url, json))
                return Reponse(codes.pop(0) if codes else 200)

            def put(self, url, json, timeout):
                appels.append(("PUT", url, json))
                return Reponse(200)

            def delete(self, url, timeout):
                appels.append(("DELETE", url, None))
                return Reponse(204)

        dossier = Path(tempfile.mkdtemp(prefix="awen-google-"))
        cle = dossier / "google-agenda.json"
        cle.write_text("{}", encoding="utf-8")
        avant = {k: self.app.config.get(k) for k in
                 ("GOOGLE_CALENDAR_ID", "GOOGLE_SERVICE_ACCOUNT_FILE")}
        self.app.config.update(GOOGLE_CALENDAR_ID="awen@group.calendar.google.com",
                               GOOGLE_SERVICE_ACCOUNT_FILE=str(cle))
        self.addCleanup(self.app.config.update, avant)
        for nom, faux in (("_session", lambda: Faux()),
                          ("_en_fond", lambda f, *a: f(*a))):
            p = mock.patch.object(agenda_google, nom, faux)
            p.start()
            self.addCleanup(p.stop)
        return appels

    def test_agenda_google_pose_puis_retire(self):
        appels = self.google()
        self.client.post("/workouts/commencer/push")
        w = Workout.query.one()
        [(methode, url, corps)] = appels
        self.assertEqual(methode, "POST")
        self.assertIn("/calendars/awen%40group.calendar.google.com/events", url)
        self.assertEqual(corps["id"], agenda_google.identifiant(w.id, w.date))
        self.assertTrue(re.fullmatch(r"[a-v0-9]{5,1024}", corps["id"]))
        self.assertEqual(corps["summary"], "Awen : termine ta séance Push")
        self.assertEqual(corps["start"], {
            "dateTime": rappels.moment(w.date).isoformat(timespec="seconds"),
            "timeZone": "Europe/Paris"})
        self.assertEqual(corps["reminders"], {"useDefault": True})

        self.client.post("/workouts/session/{}/finish".format(w.id))
        self.assertEqual(appels[-1][0], "DELETE")
        self.assertTrue(appels[-1][1].endswith("/events/" + corps["id"]))

    def test_agenda_google_annulation_et_identifiant_repris(self):
        appels = self.google(codes=[409])
        self.client.post("/workouts/commencer/legs")
        self.assertEqual([a[0] for a in appels], ["POST", "PUT"])    # rétabli
        self.assertEqual(appels[1][2]["status"], "confirmed")
        w = Workout.query.one()
        self.client.post("/workouts/session/{}/delete".format(w.id))
        self.assertEqual(appels[-1][0], "DELETE")

    def test_agenda_google_absent_ne_fait_rien(self):
        self.assertFalse(agenda_google.actif())
        with mock.patch.object(agenda_google, "_session") as session:
            self.client.post("/workouts/commencer/pull")
        session.assert_not_called()

    def test_pages(self):
        self.client.post("/workouts/commencer/reprise")
        for url in ("/", "/workouts/", "/workouts/session", "/workouts/programme",
                    "/calendar/", "/coach/", "/stats/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)


if __name__ == "__main__":
    unittest.main()
