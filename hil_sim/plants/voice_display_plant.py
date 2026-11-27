"""Edge Voice & Display Node Acoustic Envelope Plant Simulator."""

from __future__ import annotations

import math

import numpy as np


class EdgeVoiceDisplayPlant:
    """Simulates I2S MEMS microphone acoustic envelope bursts and SPI TFT render load."""

    def __init__(self, seed: int = 19) -> None:
        self.rng = np.random.default_rng(seed)
        self.time_s = 0.0
        self.current_spl_db = 44.0
        self.cpu_load_pct = 28.0
        self.sensor_disconnected = False

    def reset(self) -> None:
        self.time_s = 0.0
        self.current_spl_db = 44.0
        self.cpu_load_pct = 28.0
        self.sensor_disconnected = False

    def step(self, dt_s: float, amp_gain_pct: float, tft_bl_pct: float) -> None:
        self.time_s += dt_s
        # Periodic voice utterance envelope every 6 seconds
        phase = self.time_s % 6.0
        target_spl = 69.0 + 5.0 * math.sin(phase * 3.14) if 1.0 <= phase <= 4.0 else 43.0
        self.current_spl_db += (target_spl - self.current_spl_db) * min(1.0, dt_s * 6.0)
        self.cpu_load_pct = 24.0 + 0.12 * amp_gain_pct + 0.08 * tft_bl_pct

    def read_sensors(self) -> tuple[float, float, bool]:
        if self.sensor_disconnected:
            return (math.nan, 0.0, False)
        spl = float(self.current_spl_db + self.rng.normal(0.0, 0.4))
        cpu = float(self.cpu_load_pct + self.rng.normal(0.0, 0.5))
        return (spl, cpu, True)
