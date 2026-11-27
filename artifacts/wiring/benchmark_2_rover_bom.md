# Hardware Wiring & BOM — Dual-Mode Ultrasonic Obstacle-Avoiding Rover

## Pin Allocation Table
| Peripheral | Part Number | Signal | MCU Pin | GPIO # | Bus | Notes |
|---|---|---|---|---:|---|---|
| `l298n_drive` | `L298N-DUAL-HBRIDGE` | `ENA` | **`D3`** | 3 | MOTOR_DRIVER | Timer2 |
| `l298n_drive` | `L298N-DUAL-HBRIDGE` | `ENB` | **`D5`** | 5 | MOTOR_DRIVER | Timer0 |
| `l298n_drive` | `L298N-DUAL-HBRIDGE` | `IN1` | **`D2`** | 2 | MOTOR_DRIVER |  |
| `l298n_drive` | `L298N-DUAL-HBRIDGE` | `IN2` | **`D4`** | 4 | MOTOR_DRIVER |  |
| `l298n_drive` | `L298N-DUAL-HBRIDGE` | `IN3` | **`D7`** | 7 | MOTOR_DRIVER |  |
| `l298n_drive` | `L298N-DUAL-HBRIDGE` | `IN4` | **`D8`** | 8 | MOTOR_DRIVER |  |
| `ultrasonic_front` | `HC-SR04` | `TRIG` | **`A0`** | 14 | GPIO | ADC1 |
| `ultrasonic_front` | `HC-SR04` | `ECHO` | **`A1`** | 15 | GPIO | ADC1 |
| `pan_servo` | `SG90-9G-SERVO` | `SERVO_SIG` | **`D9`** | 9 | SERVO |  |
| `bt_hc05` | `HC-05-BT-UART` | `MCU_RX_FROM_BT_TX` | **`D0`** | 0 | UART |  |
| `bt_hc05` | `HC-05-BT-UART` | `MCU_TX_TO_BT_RX` | **`D1`** | 1 | UART |  |

## Auto-Repair Actions Applied
- Cleared conflicting manual pin overrides on 'l298n_drive' ({'ENA': 'D9', 'ENB': 'D10'}).

## Power & Battery Budget
- **Idle Current:** 62.0 mA (0.37 W)
- **Average Current:** 370.6 mA (2.47 W)
- **Peak Current:** 1359.0 mA (9.00 W)
- **MCU Onboard Regulator Load:** 119.0 / 500 mA
- **Estimated Battery Runtime (2S 18650 2000mAh Li-Ion Pack):** **4.90 hours**

## Bill of Materials (BOM)
| Ref | Part Number | Description | Qty | Notes |
|---|---|---|---:|---|
| U1 | `UNO` | Arduino Uno R3 (ATmega328P) (ATmega328P) | 1 | 5.0V logic |
| P1 | `L298N-DUAL-HBRIDGE` | L298N Dual H-Bridge + TT Gearmotors | 1 | Powered from 2S 7.4V battery rail; onboard fast clamp diodes |
| P2 | `HC-SR04` | HC-SR04 Ultrasonic Distance Sensor | 1 | 5.0V supply, GPIO |
| P3 | `SG90-9G-SERVO` | SG90 Ultrasonic Scan Servo | 1 | Driven via external 5V BEC rail; claims ATmega328P Timer1 ISR |
| P4 | `HC-05-BT-UART` | HC-05 Bluetooth SPP Module | 1 | 1k/2k divider on BT RX; disconnect TX jumper during Uno USB upload |
| BAT1 | `2S-18650-2000MAH-LI-ION-PACK` | 2S 18650 2000mAh Li-Ion Pack (7.4V, 2000mAh) | 1 | Est. runtime 4.9h |