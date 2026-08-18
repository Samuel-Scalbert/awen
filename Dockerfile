# Image de production d'Awen.
#
# Servie par gunicorn, pas par le serveur de développement Flask : ce dernier
# est mono-thread, non conçu pour tourner en continu, et son débogueur exposé
# sur le réseau est une porte ouverte.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Paris

# tzdata : sans lui le conteneur vit en UTC, et l'app calcule des « aujourd'hui »
# (séance du jour, veille emploi) qui basculeraient deux heures trop tôt le soir.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# L'app ne doit jamais écrire en dehors de /app/data (volume monté).
RUN useradd --create-home --uid 1000 awen \
 && mkdir -p /app/data \
 && chown -R awen:awen /app
USER awen

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/', timeout=4).status==200 else 1)"

# Un seul worker, plusieurs threads : la base est en SQLite, et plusieurs
# processus qui écrivent le même fichier finissent en « database is locked ».
# Pour un usage personnel (toi + l'ESP32), 8 threads sont largement suffisants.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", \
     "--workers", "1", "--threads", "8", "--timeout", "120", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "run:app"]
