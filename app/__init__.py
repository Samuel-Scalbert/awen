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

    app.register_blueprint(main_bp)
    app.register_blueprint(workout_bp)
    app.register_blueprint(meals_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(esp32_bp)

    with app.app_context():
        db.create_all()
        from .seed import seed_default_recipes
        seed_default_recipes()

    return app
