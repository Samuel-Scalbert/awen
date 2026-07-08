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


_QTY_RE = re.compile(
    r"(?P<lo>\d+(?:[.,]\d+)?)"
    r"(?:\s*-\s*(?P<hi>\d+(?:[.,]\d+)?))?"
    r"\s*(?P<unit>g|kg|ml|cl|l)?"
    r"(?!\s*%)(?=[\s,.)]|$)", re.IGNORECASE)


def _fmt_qty(value):
    return f"{round(value, 1):g}".replace(".", ",")


def scale_item(text, factor):
    """Multiplie les quantités d'un ingrédient par le facteur de portions.

    « 400 ml de lait » ×7 → « 2,8 L de lait » ; « 35-40 g de miel » ×2 →
    « 70-80 g de miel ». Les items sans nombre restent tels quels.
    """
    if abs(factor - 1) < 1e-9:
        return text

    def repl(m):
        values = [float(m.group("lo").replace(",", ".")) * factor]
        if m.group("hi"):
            values.append(float(m.group("hi").replace(",", ".")) * factor)
        unit = (m.group("unit") or "")
        if unit.lower() in ("g", "ml") and min(values) >= 1000:
            values = [v / 1000 for v in values]
            unit = "kg" if unit.lower() == "g" else "L"
        out = "-".join(_fmt_qty(v) for v in values)
        return out + (f" {unit}" if unit else "")

    return _QTY_RE.sub(repl, text)


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

    ?p<id>=N choisit le nombre de portions voulues par recette (0 = exclue) ;
    les quantités sont recalculées depuis les portions de la recette. Le tri
    frigo (« j'ai déjà ») se fait côté client, rien n'est persisté.
    """
    recipes = Recipe.query.order_by(Recipe.name).all()
    portions = {}
    for r in recipes:
        default = 7 if "shake" in (r.name or "").lower() else (r.servings or 1)
        portions[r.id] = max(0, request.args.get(f"p{r.id}",
                                                 default=default, type=int))
    sections = []
    for r in recipes:
        if portions[r.id] <= 0:
            continue
        factor = portions[r.id] / (r.servings or 1)
        sections.append({
            "name": r.name,
            "portions": portions[r.id],
            "lines": [scale_item(i, factor)
                      for i in parse_ingredients(r.ingredients)],
        })
    return render_template("courses.html", recipes=recipes, portions=portions,
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
        servings=int(request.form.get("servings") or 1),
    )
    db.session.add(r)
    db.session.commit()
    return redirect(url_for("meals.list_meals"))
