"""La météo de l'afficheur : la position du .env, la pluie qui vient.

    python -m unittest tests.test_meteo
"""
import unittest
from unittest import mock

from app import create_app
from app.config import Config
from app.services import weather


class ConfigTest(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WEATHER_LAT, WEATHER_LON = 48.8637, 2.2769


class Reponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


# Le 21/10/2026 à 16 h : une averse à 8 h (35 %), presque rien ensuite.
OPEN_METEO = {
    "current": {"temperature_2m": 14.4, "weather_code": 3},
    "daily": {"temperature_2m_min": [8.4], "temperature_2m_max": [14.6]},
    "hourly": {"precipitation_probability": [10, 5, 3, 3, 0, None, 0, 0, 0, 0, 0, 0]},
}


class MeteoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(ConfigTest)

    def setUp(self):
        weather._cache.update(at=0, data=None)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)

    def test_la_pluie_qui_vient(self):
        with mock.patch.object(weather.requests, "get",
                               return_value=Reponse(OPEN_METEO)) as get:
            m = weather.today()
        self.assertEqual((m["now_c"], m["min_c"], m["max_c"]), (14, 8, 15))
        # Le plus haut des douze prochaines heures, pas l'averse du matin.
        self.assertEqual(m["rain_pct"], 10)
        self.assertEqual(m["label"], "COUVERT")
        params = get.call_args.kwargs["params"]
        self.assertEqual((params["latitude"], params["longitude"]), (48.8637, 2.2769))
        self.assertEqual(params["forecast_hours"], weather.HEURES_PLUIE)

    def test_sans_prevision_horaire(self):
        sans = dict(OPEN_METEO, hourly={})
        with mock.patch.object(weather.requests, "get", return_value=Reponse(sans)):
            self.assertEqual(weather.today()["rain_pct"], 0)


if __name__ == "__main__":
    unittest.main()
