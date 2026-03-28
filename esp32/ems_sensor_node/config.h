#ifndef CONFIG_H
#define CONFIG_H

// ---- WiFi ----
#define WIFI_SSID     "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"

// ---- MQTT ----
#define MQTT_BROKER   "192.168.1.100"   // Raspberry Pi IP address
#define MQTT_PORT     1883
#define MQTT_CLIENT   "esp32-ems-01"
#define TOPIC_BATTERY "ems/battery"

// 3 AC load groups — each maps to a separate PZEM-004T sensor
// For a single ESP32 with one PZEM, set LOAD_GROUP to the one it monitors.
// For multiple ESP32s, each gets a different LOAD_GROUP.
#define LOAD_GROUP    "load1"
#define TOPIC_AC      "ems/ac/" LOAD_GROUP

// ---- PZEM-004T (Hardware Serial 2) ----
#define PZEM_RX_PIN   16   // GPIO16 = RX for PZEM
#define PZEM_TX_PIN   17   // GPIO17 = TX for PZEM

// ---- Victron SmartShunt VE.Direct (Hardware Serial 1) ----
#define VEDIRECT_RX_PIN  4   // GPIO4 = RX (SmartShunt TX -> ESP32 RX)
#define VEDIRECT_BAUD    19200

// ---- Timing ----
#define PUBLISH_INTERVAL_MS  500   // Send data every 0.5 seconds
#define WIFI_RETRY_DELAY_MS  5000
#define MQTT_RETRY_DELAY_MS  2000

#endif
