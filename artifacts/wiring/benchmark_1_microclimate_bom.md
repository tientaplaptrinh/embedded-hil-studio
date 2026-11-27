# Hardware Wiring & BOM — Automated Micro-Climate Habitat Controller

## Pin Allocation Table
| Peripheral | Part Number | Signal | MCU Pin | GPIO # | Bus | Notes |
|---|---|---|---|---:|---|---|
| `sht31_sensor` | `SHT31-D` | `SDA` | **`GPIO21`** | 21 | I2C | Shared I2C0 |
| `sht31_sensor` | `SHT31-D` | `SCL` | **`GPIO22`** | 22 | I2C | Shared I2C0 |
| `substrate_adc` | `CAPACITIVE_MOISTURE_V1_2` | `AOUT` | **`GPIO32`** | 32 | ADC | ADC1 |
| `mist_relay` | `SRD-05VDC-SL-C` | `COIL_DRIVE` | **`GPIO16`** | 16 | GPIO |  |
| `exhaust_fan` | `NF-A4x10-5V-PWM` | `PWM_CTRL` | **`GPIO4`** | 4 | PWM | ADC2 |

## Auto-Repair Actions Applied
- Cleared conflicting manual pin overrides on 'substrate_adc' ({'AOUT': 'GPIO25'}).
- Cleared conflicting manual pin overrides on 'mist_relay' ({'COIL_DRIVE': 'GPIO34'}).
- Inserted opto-isolated N-MOSFET driver + 1N4007 flyback diode for inductive load 'mist_relay'.

## Power & Battery Budget
- **Idle Current:** 45.7 mA (0.17 W)
- **Average Current:** 283.8 mA (1.10 W)
- **Peak Current:** 717.8 mA (3.02 W)
- **MCU Onboard Regulator Load:** 332.8 / 800 mA
- **Estimated Battery Runtime (2S 18650 Li-Ion UPS Pack):** **13.04 hours**

## Bill of Materials (BOM)
| Ref | Part Number | Description | Qty | Notes |
|---|---|---|---:|---|
| U1 | `ESP32DEV` | ESP32 DevKit V1 (38-Pin WROOM-32) (ESP32-D0WDQ6) | 1 | 3.3V logic |
| P1 | `SHT31-D` | Sensirion SHT31-D I2C Temp/RH Sensor | 1 | 3.3V supply, I2C |
| P2 | `CAPACITIVE_MOISTURE_V1_2` | Backup Capacitive Humidity Probe | 1 | 3.3V supply, ADC |
| P3 | `SRD-05VDC-SL-C` | Ultrasonic Mist Atomizer Relay | 1 | Auto-inserted PC817/AO3400 MOSFET driver + 1N4007 flyback diode |
| Q_DRV3 | `PC817-AO3400-1N4007` | Opto-Isolated N-MOSFET Low-Side Driver + Flyback Diode | 1 | Inductive transient clamp for mist_relay |
| P4 | `NF-A4x10-5V-PWM` | 5V Brushless PWM Exhaust Fan | 1 | Built-in hall driver + flyback protection on 5V rail |
| BAT1 | `2S-18650-LI-ION-UPS-PACK` | 2S 18650 Li-Ion UPS Pack (7.4V, 2600mAh) | 1 | Est. runtime 13.04h |