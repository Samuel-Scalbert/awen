"""La pochette servie à l'afficheur, à la taille qu'il demande.

    python -m unittest tests.test_pochette

L'ancien firmware n'envoie aucun paramètre et attend 112 px en blocs ; celui
à trois pages demande sa taille. Les deux doivent recevoir exactement le
nombre d'octets qu'ils lisent, sinon la carte affiche une image décalée.
"""
import io
import unittest
from unittest import mock

from PIL import Image

from app import create_app
from app.config import Config
from app.services import spotify as spotify_svc


class ConfigTest(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    ESP32_API_KEY = "cle"


class Image300:
    """Une pochette de 300 px, comme celles que sert Spotify."""

    def __init__(self):
        buf = io.BytesIO()
        Image.new("RGB", (300, 300), (200, 40, 40)).save(buf, "JPEG")
        self.content = buf.getvalue()

    def raise_for_status(self):
        pass


class PochetteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(ConfigTest)

    def setUp(self):
        spotify_svc._cover.update(url=None, data=None)
        p1 = mock.patch.object(spotify_svc, "now_playing",
                               return_value={"device": "PC",
                                             "art_url": "https://x/a.jpg"})
        p2 = mock.patch.object(spotify_svc.requests, "get",
                               return_value=Image300())
        p1.start()
        self.get = p2.start()
        self.addCleanup(p1.stop)
        self.addCleanup(p2.stop)
        self.client = self.app.test_client()

    def _taille(self, suite=""):
        r = self.client.get("/api/esp32/cover?key=cle" + suite)
        self.assertEqual(r.status_code, 200)
        cote = int(r.headers["X-Cover-Size"])
        self.assertEqual(len(r.data), cote * cote * 2)
        return cote

    def test_ancien_afficheur(self):
        self.assertEqual(self._taille(), 112)

    def test_taille_demandee(self):
        self.assertEqual(self._taille("&size=144"), 144)

    def test_taille_bornee(self):
        self.assertEqual(self._taille("&size=999"), spotify_svc.COVER_MAX)
        self.assertEqual(self._taille("&size=8"), spotify_svc.COVER_MIN)

    def test_empreinte_annoncee(self):
        """La carte renvoie l'empreinte reçue de /pages : on sert cette
        pochette-là, sans redemander à Spotify ce qui joue."""
        from app.routes import esp32 as esp32_routes
        esp32_routes._pochettes["abc123"] = "https://x/b.jpg"
        self.addCleanup(esp32_routes._pochettes.pop, "abc123", None)
        spotify_svc.now_playing.reset_mock()
        self._taille("&size=144&tag=abc123")
        spotify_svc.now_playing.assert_not_called()
        self.assertEqual(self.get.call_args[0][0], "https://x/b.jpg")

    def test_une_taille_ne_sert_pas_l_autre(self):
        """Le cache retient la taille : 144 puis 112 ne doivent pas se mêler."""
        self._taille("&size=144")
        self.assertEqual(self._taille(), 112)
        self.assertEqual(self._taille("&size=144"), 144)


if __name__ == "__main__":
    unittest.main()
