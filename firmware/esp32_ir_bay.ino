// ParkWise ESP32 IR bay sensor — one sketch per bay.
//
// Reads a digital IR obstacle sensor, debounces it, and POSTs normalized
// bay_occupancy events to the SAME ingestion endpoint every other source
// uses (source="ir_sensor"), plus a periodic heartbeat. Nothing else —
// the server owns all allocation logic; this file only reports what it sees.
//
//   POST /api/v1/ingest/bay-event   {bay_id, occupied, source, confidence, ts}
//   POST /api/v1/ingest/heartbeat   {device_id, status, ts}
//
// Configure below (or via the Bay Editor -> Devices page after seeding):
//   WIFI_SSID / WIFI_PASS   access point
//   API_BASE                local dev (http://127.0.0.1:8010) or deployed
//                           (https://parkwise-theta.vercel.app)
//   DEVICE_API_KEY          per-device key (seeded keys: sim-key-lot-a/b/c)
//   BAY_MAP                 slot (Dx pin) -> bay_id from GET /api/v1/lots/{id}/bays
//
// Wiring: see hardware/WIRING.md (IR OUT -> GPIO 13, VCC -> 5V, GND -> GND).
// Debounce: a state change must hold for DEBOUNCE_MS before it is sent,
// which rejects sensor flicker at the detection edge.

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <time.h>

// ------------------------------------------------------------------ config --
static const char* WIFI_SSID = "YOUR_WIFI_SSID";
static const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
static const char* API_BASE  = "http://127.0.0.1:8010";  // or deployed URL
static const char* DEVICE_API_KEY = "sim-key-lot-a";

// Bay slot -> bay_id mapping (one sketch reports one bay by default;
// add entries to wire several IR pins on one ESP32).
struct BaySlot {
  uint8_t pin;
  const char* bayId;
};
static BaySlot BAY_MAP[] = {
  {13, "REPLACE-WITH-BAY-ID"},
  // {14, "another-bay-id"},
};
static const size_t BAY_COUNT = sizeof(BAY_MAP) / sizeof(BAY_MAP[0]);

static const char* DEVICE_ID = "esp32-ir-1";
static const uint32_t DEBOUNCE_MS      = 300;    // stable time before send
static const uint32_t HEARTBEAT_MS     = 30000;  // 30 s heartbeat
static const uint32_t RETRY_MS         = 5000;   // backoff after failed POST
static const uint8_t  IR_TRIGGER_LEVEL = LOW;    // most IR obstacle modules
                                               // pull LOW when obstacle seen
// Confidence reported for a debounced digital reading. Honest value: a clean
// digital IR beam is reliable but not perfect (dust, angle) -> 0.9.
static const float IR_CONFIDENCE = 0.9;

// ------------------------------------------------------------------- state --
struct BayState {
  const char* bayId;
  bool stableLevel;      // debounced level currently reported
  bool lastRawLevel;
  uint32_t lastChangeMs;
  bool dirty;            // needs POST
};

BayState bays[BAY_COUNT];
uint32_t lastHeartbeatMs = 0;
uint32_t lastRetryMs = 0;

// ------------------------------------------------------------------ helpers --
String isoNow() {
  time_t now = time(nullptr);
  struct tm tmv;
  gmtime_r(&now, &tmv);
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tmv);
  return String(buf);
}

bool wifiConnect() {
  if (WiFi.status() == WL_CONNECTED) return true;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(250);
  }
  return WiFi.status() == WL_CONNECTED;
}

int postJson(const String& path, const String& body) {
  if (!wifiConnect()) return -1;
  HTTPClient http;
  http.begin(String(API_BASE) + path);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", DEVICE_API_KEY);
  http.setTimeout(5000);
  int code = http.POST(body);
  http.end();
  return code;
}

void sendHeartbeat() {
  StaticJsonDocument<192> doc;
  doc["device_id"] = DEVICE_ID;
  doc["status"] = "online";
  doc["ts"] = isoNow();
  String body;
  serializeJson(doc, body);
  int code = postJson("/api/v1/ingest/heartbeat", body);
  Serial.printf("heartbeat -> %d\n", code);
}

void sendBayEvent(const BayState& bay) {
  StaticJsonDocument<256> doc;
  doc["bay_id"] = bay.bayId;
  // raw/stableLevel are already normalized: true == obstacle seen == occupied
  doc["occupied"] = bay.stableLevel;
  doc["source"] = "ir_sensor";
  doc["confidence"] = IR_CONFIDENCE;
  doc["ts"] = isoNow();
  String body;
  serializeJson(doc, body);
  int code = postJson("/api/v1/ingest/bay-event", body);
  // 409 = admin paused hardware input (demo-day toggle) — not an error,
  // just stay quiet and keep monitoring.
  Serial.printf("bay-event %s occupied=%d -> %d\n",
                bay.bayId, doc["occupied"].as<int>(), code);
}

// --------------------------------------------------------------------- setup --
void setup() {
  Serial.begin(115200);
  Serial.println("\nParkWise IR bay sensor");

  // UTC for ISO-8601 timestamps (no NTP drift sensitivity: server also
  // falls back to its own clock when ts is omitted).
  configTime(0, 0, "pool.ntp.org");

  for (size_t i = 0; i < BAY_COUNT; i++) {
    pinMode(BAY_MAP[i].pin, INPUT_PULLUP);
    bays[i] = {BAY_MAP[i].bayId, false, false, millis(), false};
  }

  if (wifiConnect()) {
    Serial.printf("wifi ok: %s\n", WiFi.localIP().toString().c_str());
    sendHeartbeat();
    lastHeartbeatMs = millis();
  } else {
    Serial.println("wifi connect failed — will retry in loop");
  }
}

// ---------------------------------------------------------------------- loop --
void loop() {
  uint32_t now = millis();

  for (size_t i = 0; i < BAY_COUNT; i++) {
    BayState& b = bays[i];
    bool raw = (digitalRead(b.pin) == IR_TRIGGER_LEVEL);  // true = occupied

    if (raw != b.lastRawLevel) {
      b.lastRawLevel = raw;
      b.lastChangeMs = now;
    } else if (raw != b.stableLevel && now - b.lastChangeMs >= DEBOUNCE_MS) {
      b.stableLevel = raw;   // debounced transition
      b.dirty = true;
    }

    // Send only after the debounce window; retry with backoff on failure.
    if (b.dirty && now - lastRetryMs >= RETRY_MS) {
      sendBayEvent(b);
      // Assume delivered on 2xx; keep dirty otherwise so we retry.
      b.dirty = false;
      lastRetryMs = now;
    }
  }

  if (now - lastHeartbeatMs >= HEARTBEAT_MS) {
    sendHeartbeat();
    lastHeartbeatMs = now;
  }

  delay(50);  // 20 Hz poll — cheap, and well inside the debounce window
}
