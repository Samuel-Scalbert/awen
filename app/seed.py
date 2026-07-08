"""Recettes de départ, chargées une seule fois si la table est vide."""
from .models import db, Recipe

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
        notes=(
            "Portions : 1\n"
            "Option jours d'entraînement : +30 g de whey (+120 kcal, +24 g prot)."
        ),
    ),
]


def seed_default_recipes():
    if Recipe.query.count() > 0:
        return
    for data in DEFAULT_RECIPES:
        db.session.add(Recipe(**data))
    db.session.commit()
