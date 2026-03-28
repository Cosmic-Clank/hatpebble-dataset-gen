#ifndef MQTT_HANDLER_H
#define MQTT_HANDLER_H

#include <WiFi.h>
#include <PubSubClient.h>
#include "config.h"

/*
 * WiFi + MQTT connection manager.
 *
 * Handles initial connection and automatic reconnection for both
 * WiFi and MQTT. Call loop() every iteration to maintain connections.
 */

class MQTTHandler {
public:
    MQTTHandler() : _wifiClient(), _mqtt(_wifiClient) {}

    void begin() {
        // WiFi
        WiFi.mode(WIFI_STA);
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        Serial.printf("[WiFi] Connecting to %s", WIFI_SSID);
        while (WiFi.status() != WL_CONNECTED) {
            delay(500);
            Serial.print(".");
        }
        Serial.printf("\n[WiFi] Connected — IP: %s\n", WiFi.localIP().toString().c_str());

        // MQTT
        _mqtt.setServer(MQTT_BROKER, MQTT_PORT);
        _mqtt.setBufferSize(512);  // enough for our JSON payloads
        _connectMQTT();
    }

    // Call every loop() — handles reconnection
    void loop() {
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("[WiFi] Disconnected, reconnecting …");
            WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
            unsigned long start = millis();
            while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_RETRY_DELAY_MS) {
                delay(100);
            }
            if (WiFi.status() == WL_CONNECTED) {
                Serial.println("[WiFi] Reconnected");
            }
        }

        if (!_mqtt.connected()) {
            _connectMQTT();
        }
        _mqtt.loop();
    }

    // Publish a JSON string to a topic
    bool publish(const char* topic, const char* payload) {
        if (!_mqtt.connected()) return false;
        return _mqtt.publish(topic, payload);
    }

    bool isConnected() const {
        return _mqtt.connected();
    }

private:
    WiFiClient _wifiClient;
    PubSubClient _mqtt;

    void _connectMQTT() {
        Serial.printf("[MQTT] Connecting to %s:%d …\n", MQTT_BROKER, MQTT_PORT);
        int attempts = 0;
        while (!_mqtt.connected() && attempts < 5) {
            if (_mqtt.connect(MQTT_CLIENT)) {
                Serial.println("[MQTT] Connected");
                return;
            }
            Serial.printf("[MQTT] Failed (rc=%d), retrying …\n", _mqtt.state());
            delay(MQTT_RETRY_DELAY_MS);
            attempts++;
        }
        if (!_mqtt.connected()) {
            Serial.println("[MQTT] Could not connect after 5 attempts, will retry in loop");
        }
    }
};

#endif
