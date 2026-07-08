"""Point d'entrée Awen."""
from app import create_app

app = create_app()

if __name__ == "__main__":
    # host=0.0.0.0 pour être joignable par l'ESP32 sur le réseau local
    app.run(host="0.0.0.0", port=5000, debug=True)
