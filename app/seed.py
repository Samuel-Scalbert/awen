"""Données de départ (recettes, programme PPL), chargées si les tables sont vides."""
import re

from sqlalchemy import text as sqltext

from .models import db, Recipe, ProgramExercise

DEFAULT_RECIPES = [
    dict(
        name="Saumon croustillant bowl (spicy salmon rice bowl)",
        ingredients=(
            "Saumon : 600 g de saumon, ail en poudre, paprika, huile d'olive, 40 g de panko\n"
            "Salade concombre : 400 g de concombre, vinaigre de riz, 50 ml de sauce soja, "
            "10 g de miel, 10 g de purée de piment, gingembre\n"
            "Sauce spicy : 50 g de sriracha, 50 g de mayonnaise light, 100 g de fromage blanc 0 %, "
            "20 ml de jus de citron vert\n"
            "Base : 600 g de riz cuit"
        ),
        steps=(
            "1. Couper le saumon en cubes. Assaisonner avec ail en poudre, paprika et un filet d'huile d'olive.\n"
            "2. Enrober les cubes de panko.\n"
            "3. Cuire au four sur une plaque avec papier cuisson jusqu'à ce que le saumon soit doré "
            "et cuit à cœur (~200 °C, 12-15 min).\n"
            "4. Salade concombre : trancher les concombres dans un contenant, ajouter vinaigre de riz, "
            "sauce soja, miel, purée de piment et gingembre. Fermer et secouer.\n"
            "5. Sauce spicy : mélanger mayo light, sriracha, jus de citron vert et fromage blanc.\n"
            "6. Assembler 4 boîtes : riz, salade de concombre, cubes de saumon, filet de sauce spicy."
        ),
        calories=650, protein_g=39, carbs_g=60, fat_g=25, is_favorite=True,
        servings=4,
        notes=(
            "Portions : 4 · Cuisine : japonisant · Cuisson : four\n"
            "Conservation : 3-4 jours au frigo. Réchauffer riz + saumon, garder concombre et sauce à part."
        ),
    ),
    dict(
        name="Snickers maison (barres petit-déj)",
        ingredients=(
            "6 galettes de riz (fleur de sel), 100 g de beurre de cacahuète sans sucre, 35-40 g de miel, "
            "40-50 g de cacahuètes, 70 g de chocolat noir sans sucre, une pincée de fleur de sel."
        ),
        steps=(
            "1. Écraser les 6 galettes de riz dans un saladier.\n"
            "2. Mélanger le beurre de cacahuète et le miel jusqu'à consistance lisse.\n"
            "3. Ajouter le mélange et les cacahuètes aux galettes écrasées, bien mélanger jusqu'à "
            "obtenir une pâte cohésive.\n"
            "4. Presser fermement sur du papier cuisson en une plaque plate et régulière.\n"
            "5. Faire fondre le chocolat noir et le répartir sur le dessus.\n"
            "6. Saupoudrer de fleur de sel.\n"
            "7. 10 min au frigo pour figer le chocolat.\n"
            "8. Couper en 8 barres."
        ),
        calories=190, protein_g=6, carbs_g=16, fat_g=13, is_favorite=True,
        servings=8,
        notes=(
            "Portions : 8 barres · Sans cuisson\n"
            "Rôle : 2 barres + un verre de lait entier = le petit-déjeuner des matins sans appétit (~570 kcal).\n"
            "Conservation : 1 semaine au frigo dans une boîte hermétique."
        ),
    ),
    dict(
        name="Shake prise de masse",
        ingredients=(
            "400 ml de lait entier, 1 banane (120 g), 60 g d'avoine, 20 g de beurre de cacahuète.\n"
            "Option jours d'entraînement : +30 g de whey."
        ),
        steps="Tout au blender.",
        calories=710, protein_g=27, carbs_g=91, fat_g=29, is_favorite=True,
        servings=1,
        notes=(
            "Portions : 1\n"
            "Option jours d'entraînement : +30 g de whey (+120 kcal, +24 g prot)."
        ),
    ),
]


def ensure_recipe_servings():
    """Migration légère : ajoute la colonne servings aux bases existantes.

    Backfill depuis la mention « Portions : N » des notes quand elle existe.
    """
    cols = [row[1] for row in
            db.session.execute(sqltext("PRAGMA table_info(recipes)"))]
    if "servings" not in cols:
        db.session.execute(
            sqltext("ALTER TABLE recipes ADD COLUMN servings INTEGER"))
        db.session.commit()
    for r in Recipe.query.filter(Recipe.servings.is_(None)):
        m = re.search(r"Portions\s*:\s*(\d+)", r.notes or "")
        r.servings = int(m.group(1)) if m else 1
    db.session.commit()


def seed_default_recipes():
    if Recipe.query.count() > 0:
        return
    for data in DEFAULT_RECIPES:
        db.session.add(Recipe(**data))
    db.session.commit()


# Programme PPL — charges de reprise (~70 % des anciens maxes).
# (session_type, position, name, slug, sets, rep_min, rep_max,
#  weight_kg, increment_kg, notes)
PPL_PROGRAM = [
    ("push", 1, "Développé incliné machine", "developpe-incline",
     4, 8, 12, 27.5, 2.5, "Ancien max : 5×11 @ 37,5 kg"),
    ("push", 2, "Chest press (machine)", "chest-press",
     4, 8, 12, 27.5, 2.5, "Machine — même gamme que le développé incliné"),
    ("push", 3, "Développé épaules", "developpe-epaules",
     4, 10, 15, 17.5, 2.5, "Ancien max : 5×15 @ 25 kg"),
    ("push", 4, "Extension triceps poulie", "triceps-poulie",
     4, 8, 12, 9, 2.5,
     "Échelle de la machine de ta salle. Ancien max ancienne salle : 5×8 @ 55 kg"),
    ("push", 5, "Extension nuque (overhead)", "extension-nuque",
     3, 12, 16, 5, 2.5, "Ancien max : 5×16 @ 7,5 kg"),
    ("pull", 1, "Low row", "low-row",
     4, 10, 15, 40, 2.5, "Ancien max : 5×15 @ 55 kg"),
    ("pull", 2, "Tractions (assistées si besoin)", "tractions",
     4, 6, 10, 45, -2.5,
     "Charge = assistance, elle baisse quand tu progresses. "
     "Ancien max : 5×13 assisté / 5×7 libre"),
    ("pull", 3, "Tirage dos prise rapprochée", "tirage-rapproche",
     4, 10, 15, 22.5, 2.5, "Ancien max : 5×15-16 @ 30 kg"),
    ("pull", 4, "Curl marteau", "curl-marteau",
     3, 8, 12, 12.5, 2.5, "Ancien max : 5×12 @ 17,5 kg"),
    ("pull", 5, "Curl inversé (avant-bras)", "curl-inverse",
     3, 12, 15, 15, 2.5, "Ancien max : 5×15 @ 20 kg"),
    ("legs", 1, "Squat", "squat",
     4, 8, 12, 55, 5, "Ancien max : 5×14 @ 80 kg"),
    ("legs", 2, "Leg extension", "leg-extension",
     4, 12, 16, 32.5, 5, "Ancien max : 5×16 @ 45 kg"),
    ("legs", 3, "Leg curl", "leg-curl",
     4, 12, 16, 32.5, 5, "Ancien max : 5×16 @ 45 kg"),
    ("legs", 4, "Mollets debout ou presse", "mollets",
     3, 12, 20, 0, 0, "Au feeling — note quand même la charge utilisée"),
    ("legs", 5, "Pompes (rappel push)", "pompes",
     3, 8, 25, 0, 0, "Au max de reps à chaque série (ancien repère : 5×12)"),
]


def seed_program():
    if ProgramExercise.query.count() > 0:
        return
    for (stype, pos, name, slug, sets, rmin, rmax, weight, inc, notes) in PPL_PROGRAM:
        db.session.add(ProgramExercise(
            session_type=stype, position=pos, name=name, slug=slug,
            block="force", sets=sets, rep_min=rmin, rep_max=rmax,
            weight_kg=weight, increment_kg=inc, rest_sec=60, notes=notes,
        ))
    db.session.commit()


# Bloc pliométrique ~20 min, placé en DÉBUT de séance : un saut se travaille
# nerveux et frais, jamais sur des jambes déjà cuites (qualité d'appui et
# sécurité). Aucune charge et increment 0 : la plyométrie progresse en hauteur
# de box, en explosivité et en temps de contact au sol — pas en kilos.
# (session_type, position, name, slug, sets, reps, rest_sec, notes)
PLYO_BLOCK = [
    ("push", 1, "Saut vertical max", "plyo-saut-vertical", 4, 5, 90,
     "Bras lancés vers le haut, amorti souple. Vise la même hauteur à chaque saut."),
    ("push", 2, "Approche volley + saut", "plyo-approche", 4, 3, 90,
     "Course d'élan 3 appuis comme au filet, saut maximal, réception équilibrée."),
    ("push", 3, "Sauts groupés (tuck jumps)", "plyo-tuck", 3, 8, 60,
     "Genoux à la poitrine, contact au sol le plus court possible."),
    ("push", 4, "Rebonds chevilles (corde)", "plyo-corde", 3, 45, 60,
     "Jambes quasi tendues, tout dans la cheville — c'est le ressort du saut. "
     "Série tenue au chrono."),

    ("pull", 1, "Box jumps", "plyo-box-jump", 4, 5, 90,
     "Monte sur la box, redescends en marchant. Augmente la hauteur quand 5 sauts passent nets."),
    ("pull", 2, "Bondissements latéraux", "plyo-lateral", 3, 8, 90,
     "8 par côté. Stabilité à la réception : utile en défense au volley."),
    ("pull", 3, "Saut en longueur départ arrêté", "plyo-longueur", 3, 5, 90,
     "Mesure la distance de temps en temps : c'est ton indicateur de puissance."),
    ("pull", 4, "Rebonds chevilles (corde)", "plyo-corde", 3, 45, 60,
     "Jambes quasi tendues, tout dans la cheville. Série tenue au chrono."),

    ("legs", 1, "Sauts en contrebas (depth jumps)", "plyo-depth", 4, 4, 90,
     "Box 30-40 cm : descends, touche le sol et renvoie immédiatement. "
     "Le plus efficace pour la détente — et le plus exigeant, d'où 4 reps."),
    ("legs", 2, "Squat jumps", "plyo-squat-jump", 3, 5, 90,
     "Descente à mi-cuisse, extension complète. Avant le squat lourd, jamais après."),
    ("legs", 3, "Fentes sautées", "plyo-fentes", 3, 6, 90,
     "6 par jambe, alternées en l'air."),
    ("legs", 4, "Rebonds chevilles (corde)", "plyo-corde", 3, 45, 60,
     "Jambes quasi tendues, tout dans la cheville. Série tenue au chrono."),
]


# Exercices tenus au chrono plutôt que comptés en répétitions. Une seule
# source de vérité, utilisée par le seed comme par la migration — sinon une
# base neuve et une base migrée finiraient avec des réglages différents.
DURATION_SLUGS = {"plyo-corde"}


def ensure_program_block():
    """Migration douce : ajoute les colonnes `block`, `unit` et `active`."""
    cols = [row[1] for row in
            db.session.execute(sqltext("PRAGMA table_info(program_exercises)"))]
    if "block" not in cols:
        db.session.execute(sqltext(
            "ALTER TABLE program_exercises ADD COLUMN block VARCHAR(10)"))
    if "unit" not in cols:
        db.session.execute(sqltext(
            "ALTER TABLE program_exercises ADD COLUMN unit VARCHAR(6)"))
    if "active" not in cols:
        db.session.execute(sqltext(
            "ALTER TABLE program_exercises ADD COLUMN active BOOLEAN"))
    db.session.commit()
    ProgramExercise.query.filter(ProgramExercise.block.is_(None)).update(
        {"block": "force"}, synchronize_session=False)
    ProgramExercise.query.filter(ProgramExercise.unit.is_(None)).update(
        {"unit": "reps"}, synchronize_session=False)
    ProgramExercise.query.filter(ProgramExercise.active.is_(None)).update(
        {"active": True}, synchronize_session=False)
    db.session.commit()

    # Les rebonds de chevilles se tiennent au chrono : compter 30 sauts en
    # sautant à la corde est impraticable (retour du terrain, 13/08).
    for pe in ProgramExercise.query.filter(
            ProgramExercise.slug.in_(DURATION_SLUGS)):
        if pe.unit != "sec":
            pe.unit = "sec"
            pe.rep_min = pe.rep_max = 45
    db.session.commit()


def seed_plyo_block():
    if ProgramExercise.query.filter_by(block="plyo").count() > 0:
        return
    for (stype, pos, name, slug, sets, reps, rest, notes) in PLYO_BLOCK:
        db.session.add(ProgramExercise(
            session_type=stype, block="plyo", position=pos, name=name,
            slug=slug, sets=sets, rep_min=reps, rep_max=reps, weight_kg=0,
            increment_kg=0, rest_sec=rest, notes=notes,
            unit="sec" if slug in DURATION_SLUGS else "reps",
        ))
    db.session.commit()


def apply_pull_feedback():
    """Ajustements de la séance Pull, issus des commentaires du 17/08.

    Idempotent : chaque changement n'est appliqué que s'il ne l'est pas déjà,
    la fonction peut donc tourner à chaque démarrage sans rien casser.

    Le principe pour les remplacements : « seated row » est le même mouvement
    que l'ancien « low row », on renomme donc l'exercice existant pour qu'il
    garde son historique et sa charge. Le « pec fly rear delt » est un
    mouvement nouveau : il reçoit une fiche neuve, et le tirage qu'il remplace
    est désactivé plutôt que supprimé — ses séries passées restent dans les
    statistiques.
    """
    # « Remplace par seated row donc réutilise les stats du low row »
    low = ProgramExercise.query.filter_by(slug="low-row").first()
    if low and low.name != "Seated row":
        low.name = "Seated row"
        low.notes = ("Anciennement « low row » : même mouvement, l'historique "
                     "et la charge sont conservés.")
        low.position = 2

    # « Remplace par un pec fly rear delt, c'est le premier exercice que je fais »
    tirage = ProgramExercise.query.filter_by(slug="tirage-rapproche").first()
    if tirage and tirage.active:
        tirage.active = False
    if not ProgramExercise.query.filter_by(slug="pec-fly-rear-delt").first():
        db.session.add(ProgramExercise(
            session_type="pull", block="force", position=1,
            name="Pec fly / rear delt", slug="pec-fly-rear-delt",
            sets=4, rep_min=10, rep_max=15, weight_kg=0, increment_kg=2.5,
            rest_sec=60, unit="reps", active=True,
            notes="Premier exercice de la séance. Charge à régler à la première "
                  "séance, la progression prendra le relais ensuite.",
        ))

    # « Passe à 4 sets et écris bien que c'est au dependant curl »
    marteau = ProgramExercise.query.filter_by(slug="curl-marteau").first()
    if marteau and marteau.sets != 4:
        marteau.sets = 4
        marteau.notes = "Machine dependant arm curl."

    # « Les curl sont à la poulie »
    inverse = ProgramExercise.query.filter_by(slug="curl-inverse").first()
    if inverse and "poulie" not in (inverse.notes or ""):
        inverse.name = "Curl inversé (poulie)"
        inverse.notes = "À la poulie, pas à la barre."

    # « 60 sec pour la plyo repos »
    ProgramExercise.query.filter_by(block="plyo").update(
        {"rest_sec": 60}, synchronize_session=False)

    db.session.flush()

    # Renumérotation : les remplacements ci-dessus laissent deux exercices sur
    # la même position, ce qui rendrait les flèches ↑↓ de la page Programme
    # imprévisibles. On repart de 1 pour chaque bloc, en conservant l'ordre
    # actuellement affiché.
    for stype in ("push", "pull", "legs"):
        for block in ("force", "plyo"):
            rows = (ProgramExercise.query
                    .filter_by(session_type=stype, block=block)
                    .filter(ProgramExercise.active.is_(True))
                    .order_by(ProgramExercise.position, ProgramExercise.id).all())
            for i, pe in enumerate(rows, 1):
                pe.position = i

    db.session.commit()
