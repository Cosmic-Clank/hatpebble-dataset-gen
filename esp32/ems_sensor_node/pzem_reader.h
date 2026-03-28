#ifndef PZEM_READER_H
#define PZEM_READER_H

#include <PZEM004Tv30.h>
#include "config.h"

/*
 * PZEM-004T AC Meter Reader
 *
 * Communicates via Modbus RTU over Hardware Serial 2.
 * Reads: voltage, current, power, energy, frequency, power factor.
 * Returns NAN on read failure for any field.
 */

struct ACData {
    float voltage;       // V
    float current;       // A
    float power;         // W
    float energy;        // kWh (cumulative)
    float frequency;     // Hz
    float power_factor;  // 0.0–1.0
    bool  valid;         // true if at least voltage reads successfully
};

class PZEMReader {
public:
    PZEMReader() : _pzem(Serial2, PZEM_RX_PIN, PZEM_TX_PIN), _data{} {
        _data.valid = false;
    }

    void begin() {
        // PZEM library initializes Serial2 internally
        Serial.println("[PZEM] Initialized on UART2");
    }

    // Call this each loop iteration to refresh readings
    void read() {
        _data.voltage      = _pzem.voltage();
        _data.current      = _pzem.current();
        _data.power        = _pzem.power();
        _data.energy       = _pzem.energy();
        _data.frequency    = _pzem.frequency();
        _data.power_factor = _pzem.pf();

        // Valid if voltage is not NAN (most reliable indicator)
        _data.valid = !isnan(_data.voltage);
    }

    const ACData& getData() const {
        return _data;
    }

    // Reset the energy counter on the PZEM module
    bool resetEnergy() {
        return _pzem.resetEnergy();
    }

private:
    PZEM004Tv30 _pzem;
    ACData _data;
};

#endif
