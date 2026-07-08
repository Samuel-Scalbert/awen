// Squelette ESP32 : récupère le résumé Awen et l'affiche.
// Dépendances: WiFi.h, HTTPClient.h, ArduinoJson
#include <WiFi.h>
#include <HTTPClient.h>

const char* ssid     = "TON_WIFI";
const char* password = "TON_MDP";
const char* endpoint = "http://192.168.1.XX:5000/api/esp32/summary?key=change-me";

void setup() {
  Serial.begin(115200);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\nWiFi OK");
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(endpoint);
    int code = http.GET();
    if (code == 200) {
      Serial.println(http.getString());
      // TODO: parser le JSON (ArduinoJson) et afficher sur l'écran
    }
    http.end();
  }
  delay(60000); // toutes les 60s
}
