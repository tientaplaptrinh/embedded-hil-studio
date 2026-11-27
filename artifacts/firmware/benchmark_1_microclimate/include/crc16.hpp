#pragma once
#include <stddef.h>
#include <stdint.h>

namespace ehil {

inline uint16_t crc16_ccitt(const char* data, size_t length) {
    uint16_t crc = 0xFFFFu;
    for (size_t i = 0; i < length; ++i) {
        crc ^= static_cast<uint16_t>(static_cast<uint8_t>(data[i])) << 8u;
        for (uint8_t bit = 0; bit < 8u; ++bit) {
            if ((crc & 0x8000u) != 0u) {
                crc = static_cast<uint16_t>((crc << 1u) ^ 0x1021u);
            } else {
                crc = static_cast<uint16_t>(crc << 1u);
            }
        }
    }
    return crc;
}

}  // namespace ehil
