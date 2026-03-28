#ifndef VEDIRECT_PARSER_H
#define VEDIRECT_PARSER_H

#include <Arduino.h>

/*
 * VE.Direct Text Protocol Parser
 *
 * The Victron SmartShunt sends text frames over serial at 19200 baud.
 * Each frame looks like:
 *
 *   \r\n
 *   V\t12850          (battery voltage in mV)
 *   I\t-3200          (current in mA)
 *   P\t-41            (power in W)
 *   SOC\t875          (state of charge in permille, /10 for %)
 *   CE\t-12300        (consumed energy in mAh)
 *   TTG\t852          (time-to-go in minutes)
 *   T\t28             (temperature in °C)
 *   Alarm\tOFF
 *   AR\t0             (alarm reason)
 *   Checksum\t<byte>
 *
 * We read byte-by-byte, accumulate lines, parse key=value pairs,
 * and flag when a complete frame is ready.
 */

struct BatteryData {
    float voltage;       // V
    float current;       // A
    float power;         // W
    float soc;           // %
    float consumed_ah;   // Ah
    float time_to_go;    // hours
    float temperature;   // °C
    bool  alarm;
    bool  valid;         // true when at least one full frame has been parsed
};

class VEDirectParser {
public:
    VEDirectParser() : _frameReady(false), _linePos(0) {
        _data.valid = false;
    }

    // Call this in loop() — feed every byte from Serial1
    void processByte(uint8_t b) {
        // Build up a line until we hit \n
        if (b == '\n') {
            _lineBuf[_linePos] = '\0';
            _parseLine();
            _linePos = 0;
        } else if (b == '\r') {
            // ignore CR
        } else {
            if (_linePos < sizeof(_lineBuf) - 1) {
                _lineBuf[_linePos++] = b;
            }
        }
    }

    // Returns true once per complete frame
    bool frameReady() {
        if (_frameReady) {
            _frameReady = false;
            return true;
        }
        return false;
    }

    const BatteryData& getData() const {
        return _data;
    }

private:
    BatteryData _data;
    bool _frameReady;
    char _lineBuf[64];
    size_t _linePos;

    void _parseLine() {
        // Each line is "KEY\tVALUE"
        char* tab = strchr(_lineBuf, '\t');
        if (!tab) return;

        *tab = '\0';
        const char* key = _lineBuf;
        const char* val = tab + 1;

        if (strcmp(key, "V") == 0) {
            _data.voltage = atol(val) / 1000.0f;          // mV → V
        } else if (strcmp(key, "I") == 0) {
            _data.current = atol(val) / 1000.0f;          // mA → A
        } else if (strcmp(key, "P") == 0) {
            _data.power = atof(val);                       // W
        } else if (strcmp(key, "SOC") == 0) {
            _data.soc = atol(val) / 10.0f;                // permille → %
        } else if (strcmp(key, "CE") == 0) {
            _data.consumed_ah = atol(val) / -1000.0f;     // mAh → Ah (CE is negative)
        } else if (strcmp(key, "TTG") == 0) {
            _data.time_to_go = atol(val) / 60.0f;         // minutes → hours
        } else if (strcmp(key, "T") == 0) {
            _data.temperature = atof(val);                 // °C
        } else if (strcmp(key, "Alarm") == 0) {
            _data.alarm = (strcmp(val, "ON") == 0);
        } else if (strcmp(key, "Checksum") == 0) {
            // Checksum line marks end of frame
            _data.valid = true;
            _frameReady = true;
        }
    }
};

#endif
