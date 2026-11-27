# Hardware Wiring & BOM — Edge Voice & Display Node

## Pin Allocation Table
| Peripheral | Part Number | Signal | MCU Pin | GPIO # | Bus | Notes |
|---|---|---|---|---:|---|---|
| `inmp441_mic` | `INMP441-MEMS-I2S` | `SCK` | **`GPIO4`** | 4 | I2S_RX | ADC1 |
| `inmp441_mic` | `INMP441-MEMS-I2S` | `WS` | **`GPIO5`** | 5 | I2S_RX | ADC1 |
| `inmp441_mic` | `INMP441-MEMS-I2S` | `SD` | **`GPIO6`** | 6 | I2S_RX | ADC1 |
| `max98357a_amp` | `MAX98357A-I2S-AMP` | `BCLK` | **`GPIO7`** | 7 | I2S_TX | ADC1 |
| `max98357a_amp` | `MAX98357A-I2S-AMP` | `LRC` | **`GPIO8`** | 8 | I2S_TX | ADC1 |
| `max98357a_amp` | `MAX98357A-I2S-AMP` | `DIN` | **`GPIO9`** | 9 | I2S_TX | ADC1 |
| `ili9341_tft` | `ILI9341-2.8-SPI-TFT` | `MOSI` | **`GPIO11`** | 11 | SPI | Shared SPI_DISP, ADC2 |
| `ili9341_tft` | `ILI9341-2.8-SPI-TFT` | `MISO` | **`GPIO13`** | 13 | SPI | Shared SPI_DISP, ADC2 |
| `ili9341_tft` | `ILI9341-2.8-SPI-TFT` | `SCK` | **`GPIO12`** | 12 | SPI | Shared SPI_DISP, ADC2 |
| `ili9341_tft` | `ILI9341-2.8-SPI-TFT` | `CS` | **`GPIO10`** | 10 | SPI | ADC1 |
| `ili9341_tft` | `ILI9341-2.8-SPI-TFT` | `DC` | **`GPIO14`** | 14 | SPI | ADC2 |
| `ili9341_tft` | `ILI9341-2.8-SPI-TFT` | `RST` | **`GPIO15`** | 15 | SPI | ADC2 |
| `ili9341_tft` | `ILI9341-2.8-SPI-TFT` | `LED_PWM` | **`GPIO1`** | 1 | SPI | ADC1 |

## Power & Battery Budget
- **Idle Current:** 53.3 mA (0.18 W)
- **Average Current:** 321.9 mA (1.18 W)
- **Peak Current:** 1064.0 mA (4.60 W)
- **MCU Onboard Regulator Load:** 424.0 / 800 mA
- **Estimated Battery Runtime (1S2P LiPo 3000mAh + 5V Boost UPS):** **10.01 hours**

## Bill of Materials (BOM)
| Ref | Part Number | Description | Qty | Notes |
|---|---|---|---:|---|
| U1 | `ESP32-S3-DEVKITC-1` | ESP32-S3 DevKitC-1 (N8R8 Octal PSRAM) (ESP32-S3-WROOM-1-N8R8) | 1 | 3.3V logic |
| P1 | `INMP441-MEMS-I2S` | INMP441 Omnidirectional I2S Microphone | 1 | 3.3V supply, I2S_RX |
| P2 | `MAX98357A-I2S-AMP` | MAX98357A 3.2W Class-D I2S Audio Amplifier | 1 | Powered from 5V VBUS rail with 470uF low-ESR bulk capacitor for audio bursts |
| P3 | `ILI9341-2.8-SPI-TFT` | 2.8-inch 240x320 ILI9341 SPI TFT Display | 1 | 3.3V supply, SPI |
| BAT1 | `1S2P-LIPO-3000MAH-+-5V-BOOST-UPS` | 1S2P LiPo 3000mAh + 5V Boost UPS (5.0V, 3000mAh) | 1 | Est. runtime 10.01h |