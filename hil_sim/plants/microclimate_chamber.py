"""Coupled Temperature & Relative-Humidity Micro-Climate Chamber ODE Plant."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class MicroclimateState:
    rh_pct: float = 54.0
    temp_c: float = 26.4
    mist_rate: float = 0.0
    time_s: float = 0.0


class MicroclimateChamberPlant:
    """Coupled psychrometric chamber ODE simulator with misting inertia, exhaust fan drying/cooling,
    ambient leakage, Gaussian sensor noise, and fault injection."""

    def __init__(self, seed: int = 42) -> None:
        self.rng = np.random.default_rng(seed)
        self.state = MicroclimateState()
        self.rh_ambient = 45.0
        self.temp_ambient = 24.0

        # Physical parameters
        self.tau_mist_s = 1.6          # Ultrasonic mist transport & plume inertia (s)
        self.k_mist_rh = 2.95          # %RH/s at 100% misting rate
        self.k_fan_dry = 0.16          # 1/s air-exchange drying coefficient at 100% fan
        self.k_leak_rh = 0.020         # 1/s passive enclosure humidity leakage
        self.gamma_psychro = 0.45      # %RH drop per +1°C warming

        self.q_lamp_c_s = 0.09         # Internal habitat lighting heat load (°C/s)
        self.k_evap_cool = 0.14        # Evaporative cooling from mist (°C/s)
        self.k_fan_cool = 0.15         # 1/s convective cooling at 100% exhaust fan
        self.k_wall_loss = 0.028       # 1/s conductive wall heat transfer

        # Fault & disturbance states
        self.sensor_disconnected: bool = False
        self.pending_noise_spike: float | None = None
        self.actuator_saturation_cap: float = 100.0
        self.disturbance_rh_rate: float = 0.0

    def reset(self, rh_init: float = 54.0, temp_init: float = 26.4) -> None:
        self.state = MicroclimateState(rh_pct=rh_init, temp_c=temp_init, mist_rate=0.0, time_s=0.0)
        self.sensor_disconnected = False
        self.pending_noise_spike = None
        self.actuator_saturation_cap = 100.0
        self.disturbance_rh_rate = 0.0

    def _derivatives(
        self, rh: float, temp_c: float, mist_rate: float, u_mist_norm: float, u_fan_norm: float
    ) -> tuple[float, float, float]:
        d_mist = (u_mist_norm - mist_rate) / self.tau_mist_s
        d_temp = (
            self.q_lamp_c_s
            - self.k_evap_cool * mist_rate
            - self.k_fan_cool * u_fan_norm * (temp_c - self.temp_ambient)
            - self.k_wall_loss * (temp_c - self.temp_ambient)
        )
        d_rh = (
            self.k_mist_rh * mist_rate
            - self.k_fan_dry * u_fan_norm * (rh - self.rh_ambient)
            - self.k_leak_rh * (rh - self.rh_ambient)
            - self.gamma_psychro * d_temp
            + self.disturbance_rh_rate
        )
        return d_rh, d_temp, d_mist

    def step(self, dt_s: float, mist_cmd_pct: float, fan_cmd_pct: float) -> MicroclimateState:
        eff_mist = max(0.0, min(mist_cmd_pct, self.actuator_saturation_cap)) / 100.0
        eff_fan = max(0.0, min(fan_cmd_pct, 100.0)) / 100.0

        # 4th-order Runge-Kutta integration
        s = self.state
        k1_rh, k1_t, k1_m = self._derivatives(s.rh_pct, s.temp_c, s.mist_rate, eff_mist, eff_fan)
        k2_rh, k2_t, k2_m = self._derivatives(
            s.rh_pct + 0.5 * dt_s * k1_rh,
            s.temp_c + 0.5 * dt_s * k1_t,
            s.mist_rate + 0.5 * dt_s * k1_m,
            eff_mist,
            eff_fan,
        )
        k3_rh, k3_t, k3_m = self._derivatives(
            s.rh_pct + 0.5 * dt_s * k2_rh,
            s.temp_c + 0.5 * dt_s * k2_t,
            s.mist_rate + 0.5 * dt_s * k2_m,
            eff_mist,
            eff_fan,
        )
        k4_rh, k4_t, k4_m = self._derivatives(
            s.rh_pct + dt_s * k3_rh,
            s.temp_c + dt_s * k3_t,
            s.mist_rate + dt_s * k3_m,
            eff_mist,
            eff_fan,
        )

        s.rh_pct = float(
            np.clip(s.rh_pct + (dt_s / 6.0) * (k1_rh + 2 * k2_rh + 2 * k3_rh + k4_rh), 10.0, 100.0)
        )
        s.temp_c = float(
            np.clip(s.temp_c + (dt_s / 6.0) * (k1_t + 2 * k2_t + 2 * k3_t + k4_t), 5.0, 60.0)
        )
        s.mist_rate = float(
            np.clip(s.mist_rate + (dt_s / 6.0) * (k1_m + 2 * k2_m + 2 * k3_m + k4_m), 0.0, 1.0)
        )
        s.time_s += dt_s
        return s

    def read_sensors(self) -> tuple[float, float, bool]:
        if self.sensor_disconnected:
            return (math.nan, math.nan, False)

        noisy_rh = float(self.state.rh_pct + self.rng.normal(0.0, 0.12))
        noisy_temp = float(self.state.temp_c + self.rng.normal(0.0, 0.04))
        if self.pending_noise_spike is not None:
            noisy_rh += self.pending_noise_spike
            self.pending_noise_spike = None
        return (noisy_rh, noisy_temp, True)
