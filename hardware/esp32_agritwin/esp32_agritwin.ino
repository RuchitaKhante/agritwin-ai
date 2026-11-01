#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include "DHT.h"

#include "secrets.h"

const char* ssid = WIFI_SSID;
const char* password = WIFI_PASSWORD;
const char* serverUrl = SERVER_URL;

// ==========================
// Sensor Pins
// ==========================
#define SOIL_PIN 34
#define DHT_PIN 4
#define DHT_TYPE DHT11

DHT dht(DHT_PIN, DHT_TYPE);
WebServer server(80);

// ==========================
// Soil Moisture Calibration
//
// SOIL_DRY = raw reading with the sensor in dry air
// SOIL_WET = raw reading with the prongs in a glass of water
// Read both values from the Serial Monitor or the ESP32 web page.
// ==========================
const int SOIL_DRY = 4095;   // <-- REPLACE with your dry-air raw value
const int SOIL_WET = 1500;   // <-- REPLACE with your water raw value

// ==========================
// Timer
// ==========================
unsigned long lastSendTime = 0;
const unsigned long sendInterval = 10000;

// ==========================
// Read averaged raw soil value
// ==========================
int readSoilRaw()
{
  long total = 0;

  for (int i = 0; i < 10; i++)
  {
    total += analogRead(SOIL_PIN);
    delay(5);
  }

  return total / 10;
}

// ==========================
// Convert raw reading to moisture %
// ==========================
int readSoilMoisture(int raw)
{
  float moisture =
    ((float)(SOIL_DRY - raw) /
     (SOIL_DRY - SOIL_WET)) * 100.0;

  moisture = constrain(moisture, 0.0f, 100.0f);

  return (int)(moisture + 0.5f);
}

// ==========================
// Soil condition for local webpage
// Same thresholds as the AI engine and dashboard:
// below 15 critical, 15-24 dry, 25-35 normal, above 35 wet
// ==========================
String getSoilCondition(int moisture)
{
  if (moisture < 15)
    return "Critical";

  if (moisture < 25)
    return "Dry";

  if (moisture <= 35)
    return "Normal";

  return "Wet";
}

// ==========================
// Send data to Spring Boot
// ==========================
void sendToBackend(
  int moisture,
  float temperature,
  float humidity
)
{
  if (WiFi.status() != WL_CONNECTED)
  {
    Serial.println("Wi-Fi disconnected. Reconnecting...");
    WiFi.reconnect();
    return;
  }

  HTTPClient http;

  http.setTimeout(5000);

  if (!http.begin(serverUrl))
  {
    Serial.println("Could not initialize HTTP connection.");
    return;
  }

  http.addHeader("Content-Type", "application/json");

  String json = "{";
  json += "\"moisture\":" + String(moisture) + ",";
  json += "\"temperature\":" + String(temperature, 1) + ",";
  json += "\"humidity\":" + String(humidity, 1);
  json += "}";

  Serial.println("Sending to Spring Boot:");
  Serial.println(json);

  int responseCode = http.POST(json);

  if (responseCode > 0)
  {
    Serial.print("HTTP response code: ");
    Serial.println(responseCode);

    Serial.println("Backend response: " + http.getString());
  }
  else
  {
    Serial.print("Backend connection failed: ");
    Serial.println(http.errorToString(responseCode));
  }

  http.end();
}

// ==========================
// Main webpage
// ==========================
void handleRoot()
{
  String html = R"rawliteral(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 Smart Agriculture</title>

<style>
body {
  font-family: Arial, sans-serif;
  background: #f2f5f7;
  text-align: center;
  margin: 0;
  padding: 20px;
}
.container {
  max-width: 700px;
  margin: auto;
}
.card {
  background: white;
  padding: 25px;
  margin: 20px 0;
  border-radius: 15px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.12);
}
.value {
  font-size: 36px;
  font-weight: bold;
  margin-top: 10px;
}
.label {
  font-size: 20px;
  color: #555;
}
.status {
  font-size: 18px;
  margin-top: 10px;
}
</style>

<script>
async function updateData() {
  try {
    const response = await fetch('/data');

    if (!response.ok) {
      throw new Error('Sensor reading unavailable');
    }

    const data = await response.json();

    document.getElementById('soil').textContent =
      data.soil + ' %';

    document.getElementById('raw').textContent =
      data.raw;

    document.getElementById('condition').textContent =
      data.condition;

    document.getElementById('temperature').textContent =
      data.temperature + ' °C';

    document.getElementById('humidity').textContent =
      data.humidity + ' %';

    document.getElementById('status').textContent =
      'ESP32 Online';

  } catch (error) {
    document.getElementById('status').textContent =
      'Sensor data unavailable';
  }
}

setInterval(updateData, 2000);
window.onload = updateData;
</script>
</head>

<body>
<div class="container">
  <h1>🌱 ESP32 Smart Agriculture</h1>

  <div class="card">
    <div class="label">🌱 Soil Moisture</div>
    <div class="value" id="soil">-- %</div>
  </div>

  <div class="card">
    <div class="label">Soil Sensor Raw Reading</div>
    <div class="value" id="raw">--</div>
  </div>

  <div class="card">
    <div class="label">Soil Condition</div>
    <div class="value" id="condition">--</div>
  </div>

  <div class="card">
    <div class="label">🌡 Temperature</div>
    <div class="value" id="temperature">-- °C</div>
  </div>

  <div class="card">
    <div class="label">💧 Humidity</div>
    <div class="value" id="humidity">-- %</div>
  </div>

  <div class="card">
    <div class="status" id="status">Connecting...</div>
  </div>
</div>
</body>
</html>
)rawliteral";

  server.send(200, "text/html", html);
}

// ==========================
// Live sensor data webpage API
// ==========================
void handleData()
{
  int raw = readSoilRaw();
  int moisture = readSoilMoisture(raw);

  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();

  Serial.print("Soil raw ADC: ");
  Serial.print(raw);

  Serial.print(" | Moisture: ");
  Serial.print(moisture);
  Serial.println("%");

  if (isnan(temperature) || isnan(humidity))
  {
    server.send(
      500,
      "application/json",
      "{\"error\":\"DHT11 reading failed\"}"
    );
    return;
  }

  String json = "{";
  json += "\"raw\":" + String(raw) + ",";
  json += "\"soil\":" + String(moisture) + ",";
  json += "\"condition\":\"" + getSoilCondition(moisture) + "\",";
  json += "\"temperature\":" + String(temperature, 1) + ",";
  json += "\"humidity\":" + String(humidity, 1);
  json += "}";

  server.send(200, "application/json", json);
}

// ==========================
// Setup
// ==========================
void setup()
{
  Serial.begin(115200);

  analogReadResolution(12);
  analogSetPinAttenuation(SOIL_PIN, ADC_11db);

  dht.begin();

  Serial.println();
  Serial.println("==============================");
  Serial.println("AgriTwin AI - ESP32 Sensors");
  Serial.println("==============================");

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  Serial.print("Connecting to Wi-Fi");

  unsigned long startTime = millis();

  while (
    WiFi.status() != WL_CONNECTED &&
    millis() - startTime < 20000
  )
  {
    delay(500);
    Serial.print(".");
  }

  Serial.println();

  if (WiFi.status() == WL_CONNECTED)
  {
    Serial.println("Wi-Fi connected!");

    Serial.print("ESP32 IP address: ");
    Serial.println(WiFi.localIP());
  }
  else
  {
    Serial.println("Wi-Fi connection failed.");
    Serial.println("Check Wi-Fi name and password.");
  }

  server.on("/", handleRoot);
  server.on("/data", handleData);

  server.begin();

  Serial.println("ESP32 web server started.");
}

// ==========================
// Main loop
// ==========================
void loop()
{
  server.handleClient();

  if (millis() - lastSendTime >= sendInterval)
  {
    lastSendTime = millis();

    int raw = readSoilRaw();
    int moisture = readSoilMoisture(raw);

    float temperature = dht.readTemperature();
    float humidity = dht.readHumidity();

    Serial.print("Raw soil value: ");
    Serial.print(raw);

    Serial.print(" | Moisture: ");
    Serial.print(moisture);
    Serial.println("%");

    if (!isnan(temperature) && !isnan(humidity))
    {
      sendToBackend(moisture, temperature, humidity);
    }
    else
    {
      Serial.println("DHT11 reading failed. Skipping backend send.");
    }
  }
}
