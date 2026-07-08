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
    ("push", 2, "Chest press (banc)", "chest-press",
     4, 8, 10, 7.5, 2.5, "Ancien max : 5×8 @ 10 kg"),
    ("push", 3, "Développé épaules", "developpe-epaules",
     4, 10, 15, 17.5, 2.5, "Ancien max : 5×15 @ 25 kg"),
    ("push", 4, "Extension triceps poulie", "triceps-poulie",
     4, 8, 12, 40, 2.5, "Ancien max : 5×8 @ 55 kg"),
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
            sets=sets, rep_min=rmin, rep_max=rmax, weight_kg=weight,
            increment_kg=inc, rest_sec=60, notes=notes,
        ))
    db.session.commit()
