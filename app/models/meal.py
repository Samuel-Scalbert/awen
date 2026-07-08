from . import db


class Recipe(db.Model):
    __tablename__ = "recipes"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    ingredients = db.Column(db.Text)       # une ligne par ingrédient
    steps = db.Column(db.Text)
    calories = db.Column(db.Integer)
    protein_g = db.Column(db.Float)
    carbs_g = db.Column(db.Float)
    fat_g = db.Column(db.Float)
    is_favorite = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)  # conservation, contexte...
    servings = db.Column(db.Integer, default=1)  # portions par recette
