"""Factory de l'application Awen."""
from flask import Flask
from dotenv import load_dotenv

from .config import Config
from .models import db


def create_app(config_class=Config):
    load_dotenv()
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    from .routes.main import bp as main_bp
    from .routes.workout import bp as workout_bp
    from .routes.meals import bp as meals_bp
    from .routes.calendar import bp as calendar_bp
    from .routes.esp32 import bp as esp32_bp
    from .routes.jobs import bp as jobs_bp
    from .routes.stats import bp as stats_bp
    from .routes.coach import bp as coach_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(workout_bp)
    app.register_blueprint(meals_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(esp32_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(coach_bp)

    with app.app_context():
        db.create_all()
        from .seed import (apply_pull_feedback, ensure_program_block,
                           ensure_recipe_servings, ensure_set_rir,
                           seed_default_recipes, seed_plyo_block, seed_program)
        # Les migrations de schéma d'abord : les fonctions de seed passent par
        # l'ORM, qui sélectionne toutes les colonnes du modèle — une colonne
        # encore absente de la base ferait échouer le simple comptage.
        ensure_recipe_servings()
        ensure_program_block()
        ensure_set_rir()
        seed_default_recipes()
        seed_program()
        seed_plyo_block()
        apply_pull_feedback()
        # Rattrapage unique : la base est antérieure à la distinction entre
        # « raté » et « absent », et tous ses trous venaient d'absences. Ne
        # fait rien dès qu'une qualification existe — voir attendance.py.
        from .services.attendance import backfill_absences
        backfill_absences()

    return app
