import type { TelemetryFrame } from "./types";

function crc16Ccitt(str: string): number {
  let crc = 0xffff;
  for (let i = 0; i < str.length; i++) {
    crc ^= (str.charCodeAt(i) & 0xff) << 8;
    for (let b = 0; b < 8; b++) {
      if ((crc & 0x8000) !== 0) {
        crc = ((crc << 1) ^ 0x1021) & 0xffff;
      } else {
        crc = (crc << 1) & 0xffff;
      }
    }
  }
  return crc;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function median3(a: number, b: number, c: number): number {
  const arr = [a, b, c].sort((x, y) => x - y);
  return arr[1];
}

export class StandaloneHilEngine {
  private archetype: string = "microclimate_pid";
  private dtMs = 50;
  private tMs = 0;

  // Firmware controller state
  private state: "AUTO" | "MANUAL" | "FAILSAFE" | "AVOID_SCAN" | "AVOID_TURN" = "AUTO";
  private fault = 0;
  private sp = 75.0;
  private kp = 2.5;
  private ki = 0.6;
  private kd = 0.18;
  private manualOut = 0.0;
  private integral = 0.0;
  private prevPv = 54.0;
  private primed = false;
  private medBuf: [number, number, number] = [54.0, 54.0, 54.0];
  private medIdx = 0;
  private filteredPv = 54.0;
  private stateEnterMs = 0;
  private turnDir = 1;

  // Physics plant state
  private rh = 54.0;
  private tempC = 26.4;
  private mistRate = 0.0;

  private roverX = 45.0;
  private roverY = 45.0;
  private roverTheta = 0.38;

  private voiceSpl = 44.0;

  private sensorDisconnected = false;
  private pendingSpike: number | null = null;
  private lastOut = 0.0;
  private lastOut2 = 0.0;

  configure(archetype: string, sp: number, kp: number, ki: number, kd: number): void {
    this.archetype = archetype;
    this.tMs = 0;
    this.state = "AUTO";
    this.fault = 0;
    this.sp = sp;
    this.kp = kp;
    this.ki = ki;
    this.kd = kd;
    this.integral = 0.0;
    this.primed = false;
    this.sensorDisconnected = false;
    this.pendingSpike = null;
    this.lastOut = 0.0;
    this.lastOut2 = 0.0;
    this.rh = 54.0;
    this.tempC = 26.4;
    this.mistRate = 0.0;
    this.roverX = 45.0;
    this.roverY = 45.0;
    this.roverTheta = 0.38;
    this.voiceSpl = 44.0;
  }

  sendCommand(command: "SET" | "FAULT_RESET" | "MODE", param?: string, value?: number | string): string {
    if (command === "FAULT_RESET") {
      this.fault = 0;
      this.integral = 0;
      this.primed = false;
      if (this.state === "FAILSAFE") this.state = "AUTO";
      return "FAULT_RESET";
    }
    if (command === "MODE") {
      const m = String(value).toUpperCase();
      if (m === "MANUAL") this.state = "MANUAL";
      else if (m === "AUTO" && this.state !== "FAILSAFE") this.state = "AUTO";
      return `MODE ${m}`;
    }
    const v = Number(value ?? 0);
    if (param === "setpoint") this.sp = clamp(v, -100, 500);
    else if (param === "kp") this.kp = clamp(v, 0, 50);
    else if (param === "ki") this.ki = clamp(v, 0, 25);
    else if (param === "kd") this.kd = clamp(v, 0, 25);
    else if (param === "manual_out") this.manualOut = clamp(v, 0, 100);
    return `SET ${param} ${v}`;
  }

  injectFault(opts: { sensor_disconnect?: boolean; noise_spike?: number; reset_fault?: boolean }): void {
    if (typeof opts.sensor_disconnect === "boolean") {
      this.sensorDisconnected = opts.sensor_disconnect;
    }
    if (typeof opts.noise_spike === "number") {
      this.pendingSpike = opts.noise_spike;
    }
    if (opts.reset_fault || opts.sensor_disconnect === false) {
      this.sendCommand("FAULT_RESET");
    }
  }

  private gaussianNoise(sigma: number): number {
    const u1 = Math.max(1e-7, Math.random());
    const u2 = Math.random();
    return sigma * Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
  }

  private stepPlant(dtS: number): [number, number, boolean] {
    if (this.archetype === "microclimate_pid") {
      const uMist = clamp(this.lastOut, 0, 100) / 100.0;
      const uFan = clamp(this.lastOut2, 0, 100) / 100.0;
      const deriv = (rh: number, tc: number, mr: number) => {
        const dMr = (uMist - mr) / 1.6;
        const dTc = 0.09 - 0.14 * mr - 0.15 * uFan * (tc - 24.0) - 0.028 * (tc - 24.0);
        const dRh = 2.95 * mr - 0.16 * uFan * (rh - 45.0) - 0.02 * (rh - 45.0) - 0.45 * dTc;
        return [dRh, dTc, dMr] as const;
      };
      const [k1r, k1t, k1m] = deriv(this.rh, this.tempC, this.mistRate);
      const [k2r, k2t, k2m] = deriv(this.rh + 0.5 * dtS * k1r, this.tempC + 0.5 * dtS * k1t, this.mistRate + 0.5 * dtS * k1m);
      const [k3r, k3t, k3m] = deriv(this.rh + 0.5 * dtS * k2r, this.tempC + 0.5 * dtS * k2t, this.mistRate + 0.5 * dtS * k2m);
      const [k4r, k4t, k4m] = deriv(this.rh + dtS * k3r, this.tempC + dtS * k3t, this.mistRate + dtS * k3m);
      this.rh = clamp(this.rh + (dtS / 6) * (k1r + 2 * k2r + 2 * k3r + k4r), 10, 100);
      this.tempC = clamp(this.tempC + (dtS / 6) * (k1t + 2 * k2t + 2 * k3t + k4t), 5, 60);
      this.mistRate = clamp(this.mistRate + (dtS / 6) * (k1m + 2 * k2m + 2 * k3m + k4m), 0, 1);

      if (this.sensorDisconnected) return [NaN, NaN, false];
      let sample = this.rh + this.gaussianNoise(0.12);
      if (this.pendingSpike !== null) {
        sample += this.pendingSpike;
        this.pendingSpike = null;
      }
      return [sample, this.tempC + this.gaussianNoise(0.04), true];
    }

    if (this.archetype === "rover_obstacle_fsm") {
      const vl = 36.0 * (clamp(this.lastOut, -100, 100) / 100.0);
      const vr = 36.0 * (clamp(this.lastOut2, -100, 100) / 100.0);
      const v = 0.5 * (vl + vr);
      const omega = (vr - vl) / 16.0;
      this.roverTheta += omega * dtS;
      this.roverX = clamp(this.roverX + v * Math.cos(this.roverTheta) * dtS, 12, 268);
      this.roverY = clamp(this.roverY + v * Math.sin(this.roverTheta) * dtS, 12, 268);
      if (this.sensorDisconnected) return [NaN, 0, false];
      const dxWall = Math.cos(this.roverTheta) >= 0 ? (280 - this.roverX) : this.roverX;
      const dyWall = Math.sin(this.roverTheta) >= 0 ? (280 - this.roverY) : this.roverY;
      const dist = Math.max(5, Math.min(dxWall / Math.max(0.15, Math.abs(Math.cos(this.roverTheta))), dyWall / Math.max(0.15, Math.abs(Math.sin(this.roverTheta)))) - 10.5);
      return [dist + this.gaussianNoise(0.3), 12.0, true];
    }

    // Edge voice & display node
    const phase = (this.tMs / 1000.0) % 6.0;
    const targetSpl = phase >= 1.0 && phase <= 4.0 ? 69.0 + 5.0 * Math.sin(phase * 3.14) : 43.0;
    this.voiceSpl += (targetSpl - this.voiceSpl) * Math.min(1.0, dtS * 6.0);
    if (this.sensorDisconnected) return [NaN, 0, false];
    const cpu = 24.0 + 0.12 * this.lastOut + 0.08 * this.lastOut2;
    return [this.voiceSpl + this.gaussianNoise(0.4), cpu, true];
  }

  step(): TelemetryFrame {
    const dtS = this.dtMs / 1000.0;
    this.tMs += this.dtMs;
    const [rawPv, rawPv2, valid] = this.stepPlant(dtS);

    if (!valid || Number.isNaN(rawPv)) {
      this.state = "FAILSAFE";
      this.fault |= 0x01;
      this.integral = 0.0;
      this.primed = false;
      this.lastOut = 0.0;
      this.lastOut2 = 0.0;
    } else {
      if (!this.primed) {
        this.medBuf = [rawPv, rawPv, rawPv];
        this.filteredPv = rawPv;
        this.prevPv = rawPv;
        this.primed = true;
      } else {
        this.medBuf[this.medIdx] = rawPv;
        this.medIdx = (this.medIdx + 1) % 3;
        const med = median3(this.medBuf[0], this.medBuf[1], this.medBuf[2]);
        this.filteredPv = 0.55 * med + 0.45 * this.filteredPv;
      }

      if (this.state === "FAILSAFE") {
        this.lastOut = 0.0;
        this.lastOut2 = 0.0;
      } else if (this.state === "MANUAL") {
        this.lastOut = this.manualOut;
        this.lastOut2 = 6.0;
      } else if (this.archetype === "microclimate_pid") {
        const err = this.sp - this.filteredPv;
        const pTerm = this.kp * err;
        const dMeas = -this.kd * ((this.filteredPv - this.prevPv) / dtS);
        const iCand = clamp(this.integral + this.ki * err * dtS, -40, 85);
        const rawU = pTerm + iCand + dMeas;
        const clampedU = clamp(rawU, 0, 100);
        if (!((rawU > 100 && err > 0) || (rawU < 0 && err < 0))) {
          this.integral = iCand;
        }
        let mist = clampedU;
        if (err < 2.0 && err > -0.5 && this.filteredPv - this.prevPv > 0.08) {
          mist = clamp(mist * 0.55, 0, 55);
        }
        let fan = 6.0;
        if (this.filteredPv > this.sp + 0.4) {
          fan = clamp(15 + (this.filteredPv - this.sp) * 28, 6, 100);
          mist = 0.0;
        }
        this.lastOut = mist;
        this.lastOut2 = fan;
      } else if (this.archetype === "rover_obstacle_fsm") {
        if (this.state === "AUTO") {
          if (this.filteredPv < 30.0) {
            this.state = "AVOID_SCAN";
            this.stateEnterMs = this.tMs;
            this.lastOut = 0;
            this.lastOut2 = 0;
          } else {
            this.lastOut = clamp(this.sp, 25, 90);
            this.lastOut2 = this.lastOut;
          }
        } else if (this.state === "AVOID_SCAN") {
          if (this.tMs - this.stateEnterMs >= 150) {
            this.state = "AVOID_TURN";
            this.stateEnterMs = this.tMs;
            this.turnDir = rawPv2 >= 0 ? 1 : -1;
          }
        } else if (this.state === "AVOID_TURN") {
          if (this.tMs - this.stateEnterMs >= 300 && this.filteredPv > 44.0) {
            this.state = "AUTO";
          } else {
            this.lastOut = 62 * this.turnDir;
            this.lastOut2 = -62 * this.turnDir;
          }
        }
      } else {
        const err = this.sp - this.filteredPv;
        this.lastOut = clamp(50 + this.kp * err, 5, 95);
        this.lastOut2 = this.filteredPv > 48 ? 92 : 35;
      }
      this.prevPv = this.filteredPv;
    }

    const cleanPv2 = Number.isNaN(rawPv2) ? 0.0 : rawPv2;
    const jsonBody = `{"t_ms":${this.tMs},"sp":${this.sp.toFixed(2)},"pv":${this.filteredPv.toFixed(2)},"pv2":${cleanPv2.toFixed(2)},"out":${this.lastOut.toFixed(2)},"out2":${this.lastOut2.toFixed(2)},"state":"${this.state}","fault":${this.fault}}`;
    const crcHex = crc16Ccitt(jsonBody).toString(16).toUpperCase().padStart(4, "0");
    const rawLine = `${jsonBody}*${crcHex}`;

    return {
      t_ms: this.tMs,
      sp: this.sp,
      pv: this.filteredPv,
      pv_secondary: cleanPv2,
      out: this.lastOut,
      out_secondary: this.lastOut2,
      state: this.state,
      fault: this.fault,
      crc_ok: true,
      raw_line: rawLine,
      extra: {},
    };
  }
}
