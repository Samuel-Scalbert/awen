import re

from flask import Blueprint, render_template, request, redirect, url_for

from ..models import db, Recipe

bp = Blueprint("meals", __name__, url_prefix="/meals")

# Base hebdo hors recettes (journée type du plan nutrition) : petits-déjs,
# collations du soir et dîners. Les ingrédients des recettes s'y ajoutent.
WEEKLY_STAPLES = [
    "Lait entier — 2,1 L (300 ml × 7 petits-déjs)",
    "Fromage blanc — 1,4 kg (200 g × 7 soirs)",
    "Miel — ~150 g (20 g × 7 soirs)",
    "Noix — 250 g (une poignée par soir)",
    "Viande / poisson pour les dîners — ~1,2 kg (150-200 g × 7)",
    "Féculents pour les dîners (riz, pâtes, pommes de terre…)",
    "Légumes pour les dîners",
    "Huile d'olive (généreuse sur les dîners)",
    "Whey — 120 g (optionnel : 30 g × 4 jours d'entraînement)",
]


def parse_ingredients(text):
    """Découpe le texte libre d'ingrédients en items de liste de courses.

    Une ligne par composant, préfixe « Composant : » ignoré, items séparés
    par des virgules ou des « + ».
    """
    items = []
    for line in (text or "").splitlines():
        line = line.strip().rstrip(".")
        if not line:
            continue
        if " : " in line:
            line = line.split(" : ", 1)[1]
        for part in re.split(r",|\s\+\s", line):
            part = part.strip().lstrip("+").strip()
            if part:
                items.append(part)
    return items


@bp.route("/")
def list_meals():
    recipes = Recipe.query.order_by(Recipe.is_favorite.desc(),
                                    Recipe.name).all()
    return render_template("meals.html", recipes=recipes)


@bp.route("/nutrition")
def nutrition():
    return render_template("nutrition.html")


@bp.route("/courses")
def shopping_list():
    """Liste de courses générée depuis les recettes + la base hebdo.

    ?r<id>=N choisit le nombre de batchs par recette (0 = exclue). Le tri
    frigo (« j'ai déjà ») se fait côté client, rien n'est persisté.
    """
    recipes = Recipe.query.order_by(Recipe.name).all()
    counts = {}
    for r in recipes:
        default = 7 if "shake" in (r.name or "").lower() else 1
        counts[r.id] = max(0, request.args.get(f"r{r.id}",
                                               default=default, type=int))
    sections = [{"name": r.name, "count": counts[r.id],
                 "lines": parse_ingredients(r.ingredients)}
                for r in recipes if counts[r.id] > 0]
    return render_template("courses.html", recipes=recipes, counts=counts,
                           sections=sections, staples=WEEKLY_STAPLES)


@bp.route("/add", methods=["POST"])
def add_recipe():
    r = Recipe(
        name=request.form.get("name"),
        ingredients=request.form.get("ingredients"),
        steps=request.form.get("steps"),
        calories=request.form.get("calories") or None,
        protein_g=request.form.get("protein_g") or None,
        carbs_g=request.form.get("carbs_g") or None,
        fat_g=request.form.get("fat_g") or None,
        is_favorite=bool(request.form.get("is_favorite")),
    )
    db.session.add(r)
    db.session.commit()
    return redirect(url_for("meals.list_meals"))
