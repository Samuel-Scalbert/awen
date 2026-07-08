from flask import Blueprint, render_template, request, redirect, url_for
from ..models import db, Recipe

bp = Blueprint("meals", __name__, url_prefix="/meals")


@bp.route("/")
def list_meals():
    recipes = Recipe.query.order_by(Recipe.is_favorite.desc(),
                                    Recipe.name).all()
    return render_template("meals.html", recipes=recipes)


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
