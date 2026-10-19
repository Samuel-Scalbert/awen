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

    # Les charges s'affichent en kilos, sur les crans de la machine :
    # « {{ s.weight_kg|charge(pe) }} » donne « 31,8 kg ».
    from .services import charges
    app.jinja_env.filters["charge"] = (
        lambda kg, pe=None: charges.label(kg, pe) if pe is not None
        else "{} kg".format(charges.number(kg)))
    app.jinja_env.filters["nombre"] = charges.number
    # Pour les champs de saisie : un nombre à point.
    app.jinja_env.filters["valeur"] = lambda kg, pe: "%g" % charges.shown(kg, pe)
    app.jinja_env.filters["cran"] = lambda pe: "%g" % charges.step_of(pe)
    app.jinja_env.filters["machine"] = charges.machine_label

    from .routes.main import bp as main_bp
    from .routes.workout import bp as workout_bp
    from .routes.meals import bp as meals_bp
    from .routes.calendar import bp as calendar_bp
    from .routes.esp32 import bp as esp32_bp
    from .routes.jobs import bp as jobs_bp
    from .routes.stats import bp as stats_bp
    from .routes.coach import bp as coach_bp
    from .routes.todos import bp as todos_bp
    from .routes.jarvis import bp as jarvis_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(workout_bp)
    app.register_blueprint(meals_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(esp32_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(coach_bp)
    app.register_blueprint(todos_bp)
    app.register_blueprint(jarvis_bp)

    with app.app_context():
        db.create_all()
        from .seed import (apply_october_feedback, apply_pull_feedback,
                           ensure_program_block, ensure_recipe_servings,
                           ensure_set_rir, gym_in_pounds, plyo_as_session,
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
        # Retours du 19/10/2026, chacun appliqué une seule fois : voir _once.
        plyo_as_session()
        gym_in_pounds()
        apply_october_feedback()
        # Rattrapage unique : la base est antérieure à la distinction entre
        # « raté » et « absent », et tous ses trous venaient d'absences. Ne
        # fait rien dès qu'une qualification existe — voir attendance.py.
        from .services.attendance import backfill_absences
        backfill_absences()

    return app
