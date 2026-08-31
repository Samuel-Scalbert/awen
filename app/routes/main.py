from flask import Blueprint, render_template

from ..services import charts, coach
from ..services.stats import overview

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    """Tableau de bord : les chiffres d'entraînement d'abord, puis les accès.

    Le résumé est calculé ici plutôt que sur la page Statistiques seule : c'est
    ce qu'on veut voir en ouvrant l'app, pas après deux clics.
    """
    o = overview()
    volume_chart = charts.line_chart(
        [(s["date"].strftime("%d/%m"), s["volume"]) for s in o["sessions"]],
        fmt=lambda v: f"{v / 1000:.1f} t".replace(".", ",") if v >= 1000 else f"{v:g} kg")
    return render_template("index.html", o=o, volume_chart=volume_chart,
                           headline=coach.headline(), recap=coach.weekly_recap())
