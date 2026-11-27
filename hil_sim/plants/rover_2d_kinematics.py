"""2D Differential-Drive Rover Kinematics & Ray-Cast Ultrasonic Obstacle Simulator."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class ObstacleBox:
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass
class RoverState:
    x_cm: float = 45.0
    y_cm: float = 45.0
    theta_rad: float = 0.38
    servo_deg: float = 0.0
    collisions: int = 0
    distance_traveled_cm: float = 0.0
    time_s: float = 0.0


class Rover2DKinematicsPlant:
    """2D walled obstacle course with exact ray-cast HC-SR04 ultrasonic ranging + SG90 scan."""

    def __init__(self, seed: int = 7) -> None:
        self.rng = np.random.default_rng(seed)
        self.arena_w = 280.0
        self.arena_h = 280.0
        self.rover_radius_cm = 10.5
        self.wheel_base_cm = 16.0
        self.max_wheel_speed_cm_s = 36.0
        self.obstacles: list[ObstacleBox] = [
            ObstacleBox(105.0, 85.0, 145.0, 135.0),
            ObstacleBox(175.0, 155.0, 220.0, 205.0),
            ObstacleBox(75.0, 185.0, 115.0, 225.0),
        ]
        self.state = RoverState()
        self.sensor_disconnected: bool = False

    def reset(self) -> None:
        self.state = RoverState()
        self.sensor_disconnected = False

    def _segments(self) -> list[tuple[float, float, float, float]]:
        w, h = self.arena_w, self.arena_h
        segs = [
            (0.0, 0.0, w, 0.0),
            (w, 0.0, w, h),
            (w, h, 0.0, h),
            (0.0, h, 0.0, 0.0),
        ]
        for b in self.obstacles:
            segs.extend(
                [
                    (b.x_min, b.y_min, b.x_max, b.y_min),
                    (b.x_max, b.y_min, b.x_max, b.y_max),
                    (b.x_max, b.y_max, b.x_min, b.y_max),
                    (b.x_min, b.y_max, b.x_min, b.y_min),
                ]
            )
        return segs

    def raycast_cm(self, x: float, y: float, angle_rad: float, max_range: float = 260.0) -> float:
        dx = math.cos(angle_rad)
        dy = math.sin(angle_rad)
        best = max_range

        for x1, y1, x2, y2 in self._segments():
            sx = x2 - x1
            sy = y2 - y1
            denom = dx * sy - dy * sx
            if abs(denom) < 1e-9:
                continue
            qpx = x1 - x
            qpy = y1 - y
            t = (qpx * sy - qpy * sx) / denom
            u = (qpx * dy - qpy * dx) / denom
            if t >= 0.0 and 0.0 <= u <= 1.0 and t < best:
                best = t
        return max(0.0, best - self.rover_radius_cm)

    def _check_collision(self, x: float, y: float) -> bool:
        r = self.rover_radius_cm
        if x - r <= 0.0 or x + r >= self.arena_w or y - r <= 0.0 or y + r >= self.arena_h:
            return True
        for b in self.obstacles:
            cx = min(max(x, b.x_min), b.x_max)
            cy = min(max(y, b.y_min), b.y_max)
            if math.hypot(x - cx, y - cy) < r:
                return True
        return False

    def step(self, dt_s: float, left_pwm_pct: float, right_pwm_pct: float, servo_deg: float = 0.0) -> RoverState:
        s = self.state
        s.servo_deg = float(np.clip(servo_deg, -75.0, 75.0))
        v_l = self.max_wheel_speed_cm_s * (float(np.clip(left_pwm_pct, -100.0, 100.0)) / 100.0)
        v_r = self.max_wheel_speed_cm_s * (float(np.clip(right_pwm_pct, -100.0, 100.0)) / 100.0)

        v = 0.5 * (v_l + v_r)
        omega = (v_r - v_l) / self.wheel_base_cm

        mid_theta = s.theta_rad + 0.5 * omega * dt_s
        nx = s.x_cm + v * math.cos(mid_theta) * dt_s
        ny = s.y_cm + v * math.sin(mid_theta) * dt_s
        ntheta = math.atan2(math.sin(s.theta_rad + omega * dt_s), math.cos(s.theta_rad + omega * dt_s))

        if self._check_collision(nx, ny):
            s.collisions += 1
            s.theta_rad = ntheta
        else:
            s.distance_traveled_cm += math.hypot(nx - s.x_cm, ny - s.y_cm)
            s.x_cm = nx
            s.y_cm = ny
            s.theta_rad = ntheta

        s.time_s += dt_s
        return s

    def read_sensors(self) -> tuple[float, float, bool]:
        if self.sensor_disconnected:
            return (math.nan, 0.0, False)

        s = self.state
        # Minimum forward cone distance across [-14°, 0°, +14°] ultrasonic beamwidth
        d_center = self.raycast_cm(s.x_cm, s.y_cm, s.theta_rad)
        d_fl = self.raycast_cm(s.x_cm, s.y_cm, s.theta_rad + 0.24)
        d_fr = self.raycast_cm(s.x_cm, s.y_cm, s.theta_rad - 0.24)
        front_cm = min(d_center, d_fl, d_fr) + float(self.rng.normal(0.0, 0.3))

        # Servo scan clearance differential (left minus right at ±45°)
        d_left = self.raycast_cm(s.x_cm, s.y_cm, s.theta_rad + 0.78)
        d_right = self.raycast_cm(s.x_cm, s.y_cm, s.theta_rad - 0.78)
        side_bias = d_left - d_right
        return (max(1.0, front_cm), side_bias, True)
