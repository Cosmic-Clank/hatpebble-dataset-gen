/*
 * EMS Sensor Node — ESP32 Firmware
 *
 * Reads:
 *   - Victron SmartShunt (battery) via VE.Direct on UART1
 *   - PZEM-004T (AC meter) via Modbus on UART2
 *
 * Publishes JSON to Raspberry Pi via MQTT over WiFi.
 *
 * Hardware:
 *   UART1 (GPIO 4 RX) → SmartShunt VE.Direct TX
 *   UART2 (GPIO 16 RX, GPIO 17 TX) → PZEM-004T
 */

#include <ArduinoJson.h>
#include "config.h"
#include "mqtt_handler.h"
#include "vedirect_parser.h"
#include "pzem_reader.h"

MQTTHandler   mqtt;
VEDirectParser vedirect;
PZEMReader    pzem;

unsigned long lastPublish = 0;

// ---------------------------------------------------------------
// Setup
// ---------------------------------------------------------------

void setup() {
    Serial.begin(115200);
    Serial.println("\n=== EMS Sensor Node ===");

    // VE.Direct on UART1 (RX only)
    Serial1.begin(VEDIRECT_BAUD, SERIAL_8N1, VEDIRECT_RX_PIN, -1);
    Serial.println("[VE.Direct] UART1 initialized");

    // PZEM on UART2
    pzem.begin();

    // WiFi + MQTT
    mqtt.begin();

    Serial.println("[EMS] Ready — publishing every " +
                   String(PUBLISH_INTERVAL_MS) + "ms");
}

// ---------------------------------------------------------------
// Loop
// ---------------------------------------------------------------

void loop() {
    mqtt.loop();

    // Continuously read VE.Direct bytes (non-blocking)
    while (Serial1.available()) {
        vedirect.processByte(Serial1.read());
    }

    // Publish at fixed interval
    unsigned long now = millis();
    if (now - lastPublish < PUBLISH_INTERVAL_MS) return;
    lastPublish = now;

    // Read PZEM (blocking call, ~50ms)
    pzem.read();

    // Publish battery data
    publishBattery();

    // Publish AC data
    publishAC();
}

// ---------------------------------------------------------------
// JSON builders + publishers
// ---------------------------------------------------------------

void publishBattery() {
    const BatteryData& b = vedirect.getData();

    JsonDocument doc;
    doc["time"]            = millis() / 1000.0;
    doc["battery_voltage"] = b.valid ? serialized(String(b.voltage, 4))   : serialized("null");
    doc["battery_current"] = b.valid ? serialized(String(b.current, 4))   : serialized("null");
    doc["battery_power"]   = b.valid ? serialized(String(b.power, 4))     : serialized("null");
    doc["soc"]             = b.valid ? serialized(String(b.soc, 1))       : serialized("null");
    doc["consumed_ah"]     = b.valid ? serialized(String(b.consumed_ah, 2)) : serialized("null");
    doc["time_to_go"]      = b.valid ? serialized(String(b.time_to_go, 1)) : serialized("null");
    doc["alarm_flags"]     = b.alarm ? "ON" : (const char*)nullptr;
    doc["temperature"]     = b.valid ? serialized(String(b.temperature, 2)) : serialized("null");

    char buf[384];
    serializeJson(doc, buf, sizeof(buf));

    if (mqtt.publish(TOPIC_BATTERY, buf)) {
        Serial.printf("[BAT] V=%.2f I=%.2f P=%.1f SoC=%.1f%%\n",
                      b.voltage, b.current, b.power, b.soc);
    }
}

void publishAC() {
    const ACData& a = pzem.getData();

    // Get current date/time — ESP32 doesn't have RTC, so we use uptime
    // The Pi backend can add real timestamps if needed
    unsigned long sec = millis() / 1000;
    int h = (sec / 3600) % 24;
    int m = (sec / 60) % 60;
    int s = sec % 60;
    char timeStr[16];
    snprintf(timeStr, sizeof(timeStr), "%02d:%02d:%02d", h, m, s);

    JsonDocument doc;
    doc["date"]         = "2026-01-01";   // placeholder — no RTC on ESP32
    doc["time"]         = timeStr;
    doc["ac_voltage"]   = a.valid ? serialized(String(a.voltage, 1))      : serialized("null");
    doc["ac_current"]   = a.valid ? serialized(String(a.current, 2))      : serialized("null");
    doc["active_power"] = a.valid ? serialized(String(a.power, 1))        : serialized("null");
    doc["active_energy"]= a.valid ? serialized(String(a.energy, 6))       : serialized("null");
    doc["frequency"]    = a.valid ? serialized(String(a.frequency, 2))    : serialized("null");
    doc["power_factor"] = a.valid ? serialized(String(a.power_factor, 2)) : serialized("null");

    char buf[384];
    serializeJson(doc, buf, sizeof(buf));

    if (mqtt.publish(TOPIC_AC, buf)) {
        Serial.printf("[AC]  V=%.1f I=%.2f P=%.1f F=%.2f PF=%.2f\n",
                      a.voltage, a.current, a.power, a.frequency, a.power_factor);
    }
}
