#!/usr/bin/env python3
"""Obtient un jeton de rafraichissement Spotify, une fois pour toutes.

Le tableau de bord Spotify ne fournit que le Client ID et le Client Secret.
Le jeton de rafraichissement, lui, represente TON autorisation a toi : il
n'existe qu'apres etre passe par la page de consentement, et c'est ce que
fait ce script.

    python scripts/spotify-authorize.py

Le jeton s'affiche dans ce terminal et nulle part ailleurs. Recopie-le dans
le .env du serveur ; ne le colle ni dans une conversation, ni dans un
fichier versionne. Il n'expire pas tout seul et donne un acces durable au
compte : c'est exactement le genre de secret qui a fuite par les .pyc.

PORTEES DEMANDEES

    user-read-playback-state      lire ce qui joue
    user-modify-playback-state    pause, pistes, volume

La seconde est indispensable. Un jeton cree pour une integration en lecture
seule affiche correctement mais repond 403 des qu'on appuie sur un bouton,
avec un message qui n'explique rien.
"""
import base64
import json
import sys
import urllib.parse
import urllib.request

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPE = "user-read-playback-state user-modify-playback-state"


def ask(label, default=""):
    suffix = " [{}]".format(default) if default else ""
    got = input("{}{} : ".format(label, suffix)).strip()
    return got or default


def post_form(url, fields, headers):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def main():
    print(__doc__.split("PORTEES")[0].strip())
    print("-" * 62)

    client_id = ask("Client ID")
    client_secret = ask("Client Secret")
    # Doit correspondre AU CARACTERE PRES a une URI declaree dans l'app
    # Spotify, sinon l'autorisation echoue avec INVALID_CLIENT.
    redirect = ask("Redirect URI (identique a celle declaree dans l'app)",
                   "http://127.0.0.1:8888/callback")

    if not (client_id and client_secret):
        print("\nClient ID et Client Secret sont obligatoires.")
        return 1

    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect,
        "scope": SCOPE,
    })

    print("\n1. Ouvre cette adresse et autorise l'application :\n")
    print("   " + url)
    print("\n2. Le navigateur va basculer vers ton redirect URI. La page")
    print("   affichera probablement une erreur de connexion : c'est normal,")
    print("   rien n'ecoute sur ce port. Seule compte la barre d'adresse.")
    print("\n3. Copie l'adresse COMPLETE de cette page et colle-la ici.\n")

    pasted = input("URL de retour : ").strip()
    query = urllib.parse.urlparse(pasted).query
    params = urllib.parse.parse_qs(query)

    if "error" in params:
        print("\nSpotify a refuse : {}".format(params["error"][0]))
        return 1
    if "code" not in params:
        print("\nAucun parametre « code » dans cette URL. Colle bien l'adresse")
        print("complete de la page d'erreur, pas celle de la page d'accueil.")
        return 1

    basic = base64.b64encode(
        "{}:{}".format(client_id, client_secret).encode()).decode()
    try:
        tok = post_form(TOKEN_URL, {
            "grant_type": "authorization_code",
            "code": params["code"][0],
            "redirect_uri": redirect,
        }, {"Authorization": "Basic " + basic,
            "Content-Type": "application/x-www-form-urlencoded"})
    except urllib.error.HTTPError as e:
        print("\nEchange refuse ({}) : {}".format(e.code,
                                                  e.read().decode()[:200]))
        print("Verifie que le redirect URI est identique au caractere pres.")
        return 1

    refresh = tok.get("refresh_token")
    if not refresh:
        print("\nPas de refresh_token dans la reponse. Le code d'autorisation")
        print("ne sert qu'une fois : relance le script depuis le debut.")
        return 1

    print("\n" + "=" * 62)
    print("A recopier a la fin du .env du serveur :")
    print("=" * 62)
    print("SPOTIFY_CLIENT_ID={}".format(client_id))
    print("SPOTIFY_CLIENT_SECRET={}".format(client_secret))
    print("SPOTIFY_REFRESH_TOKEN={}".format(refresh))
    print("=" * 62)
    print("Attention a la casse : SPOTIFY_REFRESH_TOKEN, tout en majuscules.")
    print("Puis sur le serveur :  cd ~/awen && docker compose up -d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
