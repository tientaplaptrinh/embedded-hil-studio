import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BatteryCharging,
  CheckCircle2,
  Cpu,
  Download,
  Gauge,
  Play,
  RefreshCw,
  ShieldAlert,
  Sliders,
  Terminal,
  Wifi,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { StandaloneHilEngine } from "./standaloneEngine";
import type { BenchmarkSummary, BlueprintResponse, TelemetryFrame } from "./types";

const MAX_BUFFER = 280;

interface StaticBundle {
  benchmarks: BenchmarkSummary[];
  blueprints: Record<string, BlueprintResponse>;
}

export default function App() {
  const [benchmarks, setBenchmarks] = useState<BenchmarkSummary[]>([]);
  const [data, setData] = useState<BlueprintResponse | null>(null);
  const [standaloneMode, setStandaloneMode] = useState<boolean | null>(null);
  const [activeTab, setActiveTab] = useState<"oscilloscope" | "pinout">("oscilloscope");
  const [latest, setLatest] = useState<TelemetryFrame | null>(null);
  const [frameCount, setFrameCount] = useState<number>(0);
  const [measuredHz, setMeasuredHz] = useState<number>(0);
  const [consoleLines, setConsoleLines] = useState<string[]>([]);
  const [svgZoom, setSvgZoom] = useState<number>(1.0);

  // Live tuner slider state
  const [spVal, setSpVal] = useState<number>(75.0);
  const [kpVal, setKpVal] = useState<number>(2.5);
  const [kiVal, setKiVal] = useState<number>(0.6);
  const [kdVal, setKdVal] = useState<number>(0.18);
  const [sensorDisconnected, setSensorDisconnected] = useState<boolean>(false);

  const framesRef = useRef<TelemetryFrame[]>([]);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rxTimestampsRef = useRef<number[]>([]);
  const totalRxRef = useRef<number>(0);
  const staticStoreRef = useRef<StaticBundle | null>(null);
  const engineRef = useRef<StandaloneHilEngine>(new StandaloneHilEngine());

  const applyBlueprintState = useCallback((bp: BlueprintResponse, useStandaloneEngine: boolean) => {
    setData(bp);
    setSpVal(bp.spec.control.setpoint);
    setKpVal(bp.spec.control.kp);
    setKiVal(bp.spec.control.ki);
    setKdVal(bp.spec.control.kd);
    setSensorDisconnected(bp.fault_state.sensor_disconnected);
    if (useStandaloneEngine) {
      const c = bp.spec.control;
      engineRef.current.configure(c.archetype, c.setpoint, c.kp, c.ki, c.kd);
    }
  }, []);

  // Detect live FastAPI backend vs static Cloud Web-HIL hosting (GitHub Pages / CDN)
  useEffect(() => {
    let cancelled = false;

    const bootstrap = async () => {
      const isStaticCdnHost = window.location.hostname.endsWith(".github.io");
      if (!isStaticCdnHost) {
        try {
          const ctrl = new AbortController();
          const timer = window.setTimeout(() => ctrl.abort(), 2200);
          const healthRes = await fetch("./api/health", { signal: ctrl.signal, cache: "no-store" });
          window.clearTimeout(timer);

          if (healthRes.ok) {
            const [bmRes, bpRes] = await Promise.all([
              fetch("./api/benchmarks"),
              fetch("./api/blueprint"),
            ]);
            if (!cancelled && bmRes.ok && bpRes.ok) {
              setBenchmarks(await bmRes.json());
              const bp: BlueprintResponse = await bpRes.json();
              applyBlueprintState(bp, false);
              setStandaloneMode(false);
              return;
            }
          }
        } catch {
          // Backend not present -> activate Standalone Cloud Web-HIL mode
        }
      }

      const staticRes = await fetch("./static_blueprints.json");
      if (!cancelled && staticRes.ok) {
        const bundle: StaticBundle = await staticRes.json();
        staticStoreRef.current = bundle;
        setBenchmarks(bundle.benchmarks);
        const initialBp = bundle.blueprints["benchmark_1_microclimate"] ?? Object.values(bundle.blueprints)[0];
        if (initialBp) {
          applyBlueprintState(initialBp, true);
        }
        setStandaloneMode(true);
      }
    };

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [applyBlueprintState]);

  const ingestFrame = useCallback((f: TelemetryFrame) => {
    framesRef.current.push(f);
    if (framesRef.current.length > MAX_BUFFER) {
      framesRef.current.shift();
    }
    totalRxRef.current += 1;
    const now = performance.now();
    rxTimestampsRef.current.push(now);
    while (rxTimestampsRef.current.length > 0 && now - rxTimestampsRef.current[0] > 1000) {
      rxTimestampsRef.current.shift();
    }
    if (totalRxRef.current % 3 === 0 || f.state === "FAILSAFE") {
      setLatest(f);
      setFrameCount(totalRxRef.current);
      setMeasuredHz(rxTimestampsRef.current.length);
      setConsoleLines((prev) => {
        const next = [...prev, `RX << ${f.raw_line}`];
        return next.length > 60 ? next.slice(-60) : next;
      });
    }
  }, []);

  // Telemetry Stream: Either Live Backend WebSocket OR Standalone 35 Hz Cloud Web-HIL Loop
  useEffect(() => {
    if (standaloneMode === null) return;

    if (standaloneMode) {
      const timerId = window.setInterval(() => {
        const f = engineRef.current.step();
        ingestFrame(f);
      }, 28);
      return () => window.clearInterval(timerId);
    }

    let active = true;
    let ws: WebSocket | null = null;
    let retryTimer: number | null = null;

    const connect = () => {
      if (!active) return;
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${window.location.host}/ws/telemetry`);

      ws.onmessage = (ev) => {
        if (!active) return;
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "history" && Array.isArray(msg.frames)) {
            framesRef.current = msg.frames.slice(-MAX_BUFFER);
            if (framesRef.current.length > 0) {
              const last = framesRef.current[framesRef.current.length - 1];
              setLatest(last);
              totalRxRef.current += framesRef.current.length;
              setFrameCount(totalRxRef.current);
            }
          } else if (msg.type === "telemetry" && msg.frame) {
            ingestFrame(msg.frame as TelemetryFrame);
          }
        } catch {
          // Ignore malformed WS message
        }
      };

      ws.onclose = () => {
        if (active) {
          retryTimer = window.setTimeout(connect, 800);
        }
      };
    };

    connect();
    return () => {
      active = false;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      if (ws) ws.close();
    };
  }, [standaloneMode, ingestFrame]);

  // 60 FPS Canvas Oscilloscope Renderer
  useEffect(() => {
    let rafId = 0;

    const draw = () => {
      const canvas = canvasRef.current;
      if (canvas && activeTab === "oscilloscope") {
        const ctx = canvas.getContext("2d");
        if (ctx) {
          const w = canvas.width;
          const h = canvas.height;
          ctx.fillStyle = "#060b16";
          ctx.fillRect(0, 0, w, h);

          const padL = 48;
          const padR = 20;
          const padT = 24;
          const padB = 30;
          const plotW = w - padL - padR;
          const plotH = h - padT - padB;

          ctx.strokeStyle = "#1e293b";
          ctx.lineWidth = 1;
          ctx.fillStyle = "#64748b";
          ctx.font = "11px monospace";

          for (let i = 0; i <= 5; i++) {
            const yVal = 100 - i * 20;
            const y = padT + (i / 5) * plotH;
            ctx.beginPath();
            ctx.moveTo(padL, y);
            ctx.lineTo(w - padR, y);
            ctx.stroke();
            ctx.fillText(`${yVal}`, 12, y + 4);
          }

          for (let j = 0; j <= 8; j++) {
            const x = padL + (j / 8) * plotW;
            ctx.beginPath();
            ctx.moveTo(x, padT);
            ctx.lineTo(x, h - padB);
            ctx.stroke();
          }

          const pts = framesRef.current;
          if (pts.length > 1) {
            const mapY = (val: number) => {
              const clamped = Math.max(-20, Math.min(115, val));
              const norm = clamped / 100;
              return padT + plotH * (1 - norm);
            };
            const mapX = (idx: number) => padL + (idx / Math.max(1, MAX_BUFFER - 1)) * plotW;
            const offset = Math.max(0, MAX_BUFFER - pts.length);

            ctx.save();
            ctx.strokeStyle = "#fbbf24";
            ctx.lineWidth = 2.2;
            ctx.setLineDash([6, 4]);
            ctx.beginPath();
            pts.forEach((p, idx) => {
              const x = mapX(offset + idx);
              const y = mapY(p.sp);
              if (idx === 0) ctx.moveTo(x, y);
              else ctx.lineTo(x, y);
            });
            ctx.stroke();
            ctx.restore();

            ctx.strokeStyle = "#34d399";
            ctx.lineWidth = 1.9;
            ctx.beginPath();
            pts.forEach((p, idx) => {
              const x = mapX(offset + idx);
              const y = mapY(p.out);
              if (idx === 0) ctx.moveTo(x, y);
              else ctx.lineTo(x, y);
            });
            ctx.stroke();

            ctx.strokeStyle = "#22d3ee";
            ctx.lineWidth = 2.8;
            ctx.beginPath();
            pts.forEach((p, idx) => {
              const x = mapX(offset + idx);
              const y = mapY(p.pv);
              if (idx === 0) ctx.moveTo(x, y);
              else ctx.lineTo(x, y);
            });
            ctx.stroke();

            const cur = pts[pts.length - 1];
            if (cur.state === "FAILSAFE") {
              ctx.fillStyle = "rgba(239, 68, 68, 0.16)";
              ctx.fillRect(padL, padT, plotW, plotH);
              ctx.fillStyle = "#fca5a5";
              ctx.font = "bold 14px monospace";
              ctx.fillText("!! HARDWARE FAILSAFE INTERLOCK ACTIVE — ACTUATORS SHUT OFF (0.0%) !!", padL + 20, padT + 26);
            }
          }

          ctx.font = "bold 11px monospace";
          ctx.fillStyle = "#fbbf24";
          ctx.fillText("-- SP (Setpoint)", padL + 12, h - 10);
          ctx.fillStyle = "#22d3ee";
          ctx.fillText("── PV (Process Variable)", padL + 150, h - 10);
          ctx.fillStyle = "#34d399";
          ctx.fillText("── OUT % (Actuator Drive)", padL + 345, h - 10);
        }
      }
      rafId = window.requestAnimationFrame(draw);
    };

    rafId = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(rafId);
  }, [activeTab]);

  const sendCommand = async (
    command: "SET" | "FAULT_RESET" | "MODE",
    param?: string,
    value?: number | string
  ) => {
    if (standaloneMode) {
      const wire = engineRef.current.sendCommand(command, param, value);
      setConsoleLines((prev) => [...prev.slice(-58), `TX >> ${wire}`]);
      return;
    }
    const res = await fetch("./api/control/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command, param, value }),
    });
    if (res.ok) {
      const body = await res.json();
      setConsoleLines((prev) => [...prev.slice(-58), `TX >> ${body.wire_line}`]);
    }
  };

  const handleSetpointChange = (nextVal: number) => {
    setSpVal(nextVal);
    void sendCommand("SET", "setpoint", nextVal);
  };

  const handleInjectDisconnect = async () => {
    setSensorDisconnected(true);
    if (standaloneMode) {
      engineRef.current.injectFault({ sensor_disconnect: true });
    } else {
      await fetch("./api/hil/inject_fault", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sensor_disconnect: true }),
      });
    }
    setConsoleLines((prev) => [...prev.slice(-58), "FAULT >> Injected SHT31/Sensor Wire Disconnect"]);
  };

  const handleRestoreSensor = async () => {
    setSensorDisconnected(false);
    if (standaloneMode) {
      engineRef.current.injectFault({ sensor_disconnect: false, reset_fault: true });
    } else {
      await fetch("./api/hil/inject_fault", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sensor_disconnect: false, reset_fault: true }),
      });
    }
    setConsoleLines((prev) => [...prev.slice(-58), "RECOVERY >> Restored Sensor + Sent FAULT_RESET"]);
  };

  const handleInjectSpike = async () => {
    if (standaloneMode) {
      engineRef.current.injectFault({ noise_spike: 24.0 });
    } else {
      await fetch("./api/hil/inject_fault", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ noise_spike: 24.0 }),
      });
    }
    setConsoleLines((prev) => [...prev.slice(-58), "FAULT >> Injected +24% Single-Sample Noise Spike"]);
  };

  const handleSelectProject = async (projectId: string) => {
    framesRef.current = [];
    if (standaloneMode && staticStoreRef.current) {
      const nextBp = staticStoreRef.current.blueprints[projectId];
      if (nextBp) {
        applyBlueprintState(nextBp, true);
      }
      return;
    }
    const res = await fetch("./api/project/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId }),
    });
    if (res.ok) {
      const bp: BlueprintResponse = await res.json();
      applyBlueprintState(bp, false);
    }
  };

  const handleExportCsv = () => {
    const rows = ["t_ms,sp,pv,pv_secondary,out,out_secondary,state,fault,crc_ok"];
    framesRef.current.forEach((f) => {
      rows.push(
        `${f.t_ms},${f.sp.toFixed(2)},${f.pv.toFixed(2)},${f.pv_secondary.toFixed(2)},${f.out.toFixed(2)},${f.out_secondary.toFixed(2)},${f.state},${f.fault},${f.crc_ok ? 1 : 0}`
      );
    });
    const blob = new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${data?.spec.project_id ?? "hil"}_telemetry.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleExportBundle = async () => {
    if (standaloneMode && data) {
      const rows = ["t_ms,sp,pv,pv_secondary,out,out_secondary,state,fault,crc_ok"];
      framesRef.current.forEach((f) => {
        rows.push(
          `${f.t_ms},${f.sp.toFixed(2)},${f.pv.toFixed(2)},${f.pv_secondary.toFixed(2)},${f.out.toFixed(2)},${f.out_secondary.toFixed(2)},${f.state},${f.fault},${f.crc_ok ? 1 : 0}`
        );
      });
      const bundle = {
        project_id: data.spec.project_id,
        platformio_ini: data.platformio_ini,
        pin_config_hpp: data.pin_config_hpp,
        wiring_markdown: data.blueprint.wiring_markdown,
        svg_diagram: data.blueprint.svg_diagram,
        telemetry_csv: rows.join("\n"),
      };
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${bundle.project_id}_platformio_bundle.json`;
      a.click();
      URL.revokeObjectURL(url);
      return;
    }

    const res = await fetch("./api/export/bundle");
    if (!res.ok) return;
    const bundle = await res.json();
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${bundle.project_id}_platformio_bundle.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const curState = latest?.state ?? "AUTO";
  const trackingErr = latest ? latest.sp - latest.pv : 0.0;
  const bp = data?.blueprint;

  const stateBadgeClasses =
    curState === "FAILSAFE"
      ? "bg-red-500/20 text-red-300 border-red-500 animate-pulse"
      : curState === "MANUAL"
      ? "bg-amber-500/20 text-amber-300 border-amber-500"
      : "bg-emerald-500/20 text-emerald-300 border-emerald-500";

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      {/* Top Industrial Lab Header */}
      <header className="border-b border-slate-800 bg-slate-900/90 px-5 py-3 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-cyan-500/15 border border-cyan-500/40 text-cyan-400">
            <Cpu className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-base font-bold tracking-tight text-slate-50">
              Embedded Hardware Architect &amp; Serial HIL Debugger
            </h1>
            <p className="text-xs text-slate-400">
              Pinout DRC • C++17 PlatformIO HAL • Closed-Loop Physics Sim • Live Serial Oscilloscope
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <select
            data-testid="project-select"
            value={data?.spec.project_id ?? "benchmark_1_microclimate"}
            onChange={(e) => void handleSelectProject(e.target.value)}
            className="bg-slate-800 border border-slate-700 text-slate-100 text-xs rounded-lg px-3 py-2 font-medium focus:outline-none focus:border-cyan-400"
          >
            {benchmarks.map((b) => (
              <option key={b.project_id} value={b.project_id}>
                {b.name} ({b.board_id})
              </option>
            ))}
          </select>

          <div
            data-testid="transport-badge"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800/80 border border-slate-700 text-xs"
          >
            <Wifi className="w-3.5 h-3.5 text-cyan-400" />
            <span className="font-mono uppercase text-cyan-300">
              {standaloneMode
                ? "CLOUD WEB-HIL SIM"
                : data?.mode === "serial"
                ? `COM:${data.serial_port}`
                : "HIL VIRTUAL SIM"}
            </span>
          </div>

          <div
            data-testid="state-badge"
            className={`px-3 py-1.5 rounded-lg border text-xs font-mono font-bold tracking-wider ${stateBadgeClasses}`}
          >
            {curState}
          </div>
        </div>
      </header>

      {/* Navigation Tabs */}
      <div className="border-b border-slate-800 bg-slate-900/50 px-5 flex items-center justify-between">
        <nav className="flex gap-2 py-2">
          <button
            type="button"
            data-testid="tab-oscilloscope"
            onClick={() => setActiveTab("oscilloscope")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition ${
              activeTab === "oscilloscope"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/50"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
            }`}
          >
            <Activity className="w-4 h-4" />
            Live Telemetry Oscilloscope &amp; Tuner
          </button>

          <button
            type="button"
            data-testid="tab-pinout"
            onClick={() => setActiveTab("pinout")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition ${
              activeTab === "pinout"
                ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/50"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
            }`}
          >
            <Cpu className="w-4 h-4" />
            Pinout &amp; DRC Inspector ({bp?.drc.passed ? "DRC PASS" : "DRC FAIL"})
          </button>
        </nav>

        <div className="flex items-center gap-4 text-xs font-mono text-slate-400">
          <span data-testid="loop-hz">Stream: {measuredHz} Hz</span>
          <span>Frames: {frameCount}</span>
          <span
            data-testid="fault-badge"
            className={latest && latest.fault > 0 ? "text-red-400 font-bold" : "text-emerald-400"}
          >
            Fault: 0x{(latest?.fault ?? 0).toString(16).padStart(2, "0").toUpperCase()}
          </span>
        </div>
      </div>

      {/* Main Content Workspace */}
      <main className="flex-1 p-5 max-w-[1600px] w-full mx-auto">
        {activeTab === "oscilloscope" ? (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
            <div
              data-testid="telemetry-panel"
              data-frame-count={frameCount}
              data-latest-sp={latest?.sp?.toFixed(2) ?? "0"}
              data-latest-pv={latest?.pv?.toFixed(2) ?? "0"}
              data-latest-out={latest?.out?.toFixed(2) ?? "0"}
              className="lg:col-span-8 flex flex-col gap-4"
            >
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5">
                  <div className="text-[11px] uppercase text-slate-400 font-semibold">Setpoint (SP)</div>
                  <div data-testid="metric-sp" className="text-xl font-mono font-bold text-amber-400 mt-1">
                    {latest ? latest.sp.toFixed(1) : spVal.toFixed(1)}
                  </div>
                </div>
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5">
                  <div className="text-[11px] uppercase text-slate-400 font-semibold">Process Var (PV)</div>
                  <div data-testid="metric-pv" className="text-xl font-mono font-bold text-cyan-400 mt-1">
                    {latest ? latest.pv.toFixed(2) : "--"}
                  </div>
                </div>
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5">
                  <div className="text-[11px] uppercase text-slate-400 font-semibold">Actuator Out</div>
                  <div data-testid="metric-out" className="text-xl font-mono font-bold text-emerald-400 mt-1">
                    {latest ? `${latest.out.toFixed(1)}%` : "0.0%"}
                  </div>
                </div>
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-3.5">
                  <div className="text-[11px] uppercase text-slate-400 font-semibold">Tracking Error</div>
                  <div data-testid="tracking-error" className="text-xl font-mono font-bold text-slate-100 mt-1">
                    {trackingErr >= 0 ? `+${trackingErr.toFixed(2)}` : trackingErr.toFixed(2)}
                  </div>
                </div>
              </div>

              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
                    <Gauge className="w-4 h-4 text-cyan-400" />
                    Multi-Channel Real-Time Serial Oscilloscope (CRC-16 Verified)
                  </div>
                  <span className="text-[11px] font-mono text-emerald-400">
                    CRC16: {latest?.crc_ok !== false ? "VALID" : "ERR"} | Secondary:{" "}
                    {latest ? latest.pv_secondary.toFixed(2) : "0.00"}
                  </span>
                </div>
                <canvas
                  ref={canvasRef}
                  data-testid="telemetry-canvas"
                  width={900}
                  height={330}
                  className="w-full h-[310px] rounded-lg border border-slate-800 bg-slate-950"
                />
              </div>

              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
                    <Terminal className="w-4 h-4 text-emerald-400" />
                    Framed JSON Serial Wire Log (`payload*CRC16`)
                  </div>
                  <button
                    type="button"
                    data-testid="btn-export-csv"
                    onClick={handleExportCsv}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-md bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-medium text-cyan-300"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Export CSV
                  </button>
                </div>
                <div
                  data-testid="serial-console"
                  className="h-36 overflow-y-auto rounded-lg bg-slate-950 border border-slate-800 p-2.5 font-mono text-[11px] text-slate-300 space-y-0.5"
                >
                  {consoleLines.slice(-18).map((ln, idx) => (
                    <div
                      key={idx}
                      className={
                        ln.startsWith("TX")
                          ? "text-amber-300"
                          : ln.startsWith("FAULT")
                          ? "text-red-400 font-semibold"
                          : ln.startsWith("RECOVERY")
                          ? "text-emerald-400 font-semibold"
                          : "text-slate-400"
                      }
                    >
                      {ln}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="lg:col-span-4 flex flex-col gap-4">
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-bold text-slate-100">
                    <Sliders className="w-4 h-4 text-cyan-400" />
                    Live Firmware Parameter Tuner
                  </div>
                  <div className="flex gap-1.5">
                    <button
                      type="button"
                      data-testid="btn-mode-auto"
                      onClick={() => void sendCommand("MODE", undefined, "AUTO")}
                      className={`px-2.5 py-1 rounded text-xs font-mono font-semibold ${
                        curState === "AUTO"
                          ? "bg-emerald-500/25 text-emerald-300 border border-emerald-500/60"
                          : "bg-slate-800 text-slate-400"
                      }`}
                    >
                      AUTO
                    </button>
                    <button
                      type="button"
                      data-testid="btn-mode-manual"
                      onClick={() => void sendCommand("MODE", undefined, "MANUAL")}
                      className={`px-2.5 py-1 rounded text-xs font-mono font-semibold ${
                        curState === "MANUAL"
                          ? "bg-amber-500/25 text-amber-300 border border-amber-500/60"
                          : "bg-slate-800 text-slate-400"
                      }`}
                    >
                      MANUAL
                    </button>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-300 font-medium">Target Setpoint (SP)</span>
                    <span data-testid="tuner-sp-val" className="font-mono font-bold text-amber-400">
                      {spVal.toFixed(1)}
                    </span>
                  </div>
                  <input
                    type="range"
                    data-testid="slider-setpoint"
                    min={45}
                    max={92}
                    step={0.5}
                    value={spVal}
                    onChange={(e) => handleSetpointChange(parseFloat(e.target.value))}
                    className="w-full h-2.5 bg-slate-800 rounded-lg accent-amber-400 cursor-pointer"
                  />
                  <div className="flex gap-2 pt-1">
                    {[60, 75, 86].map((preset) => (
                      <button
                        key={preset}
                        type="button"
                        data-testid={`btn-sp-${preset}`}
                        onClick={() => handleSetpointChange(preset)}
                        className="flex-1 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-mono text-amber-300"
                      >
                        SP {preset}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="space-y-3 pt-2 border-t border-slate-800">
                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-slate-400">Proportional Gain (Kp)</span>
                      <span className="font-mono text-cyan-300">{kpVal.toFixed(2)}</span>
                    </div>
                    <input
                      type="range"
                      data-testid="slider-kp"
                      min={0.2}
                      max={8.0}
                      step={0.1}
                      value={kpVal}
                      onChange={(e) => {
                        const v = parseFloat(e.target.value);
                        setKpVal(v);
                        void sendCommand("SET", "kp", v);
                      }}
                      className="w-full h-2 bg-slate-800 rounded-lg accent-cyan-400 cursor-pointer"
                    />
                  </div>

                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-slate-400">Integral Gain (Ki)</span>
                      <span className="font-mono text-cyan-300">{kiVal.toFixed(2)}</span>
                    </div>
                    <input
                      type="range"
                      data-testid="slider-ki"
                      min={0.0}
                      max={3.0}
                      step={0.05}
                      value={kiVal}
                      onChange={(e) => {
                        const v = parseFloat(e.target.value);
                        setKiVal(v);
                        void sendCommand("SET", "ki", v);
                      }}
                      className="w-full h-2 bg-slate-800 rounded-lg accent-cyan-400 cursor-pointer"
                    />
                  </div>

                  <div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-slate-400">Derivative Gain (Kd)</span>
                      <span className="font-mono text-cyan-300">{kdVal.toFixed(2)}</span>
                    </div>
                    <input
                      type="range"
                      data-testid="slider-kd"
                      min={0.0}
                      max={2.0}
                      step={0.05}
                      value={kdVal}
                      onChange={(e) => {
                        const v = parseFloat(e.target.value);
                        setKdVal(v);
                        void sendCommand("SET", "kd", v);
                      }}
                      className="w-full h-2 bg-slate-800 rounded-lg accent-cyan-400 cursor-pointer"
                    />
                  </div>
                </div>
              </div>

              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
                <div className="flex items-center gap-2 text-sm font-bold text-slate-100">
                  <ShieldAlert className="w-4 h-4 text-red-400" />
                  HIL Hardware Fault Injection
                </div>
                <p className="text-xs text-slate-400">
                  Verify firmware failsafe interlocks (&lt;500 ms actuator shutoff) and median/EMA noise rejection live.
                </p>

                <button
                  type="button"
                  data-testid="btn-inject-disconnect"
                  onClick={() => void handleInjectDisconnect()}
                  className={`w-full py-2.5 px-4 rounded-lg font-semibold text-xs flex items-center justify-center gap-2 border transition ${
                    sensorDisconnected
                      ? "bg-red-600/30 border-red-400 text-red-200"
                      : "bg-red-500/15 hover:bg-red-500/25 border-red-500/50 text-red-300"
                  }`}
                >
                  <AlertTriangle className="w-4 h-4" />
                  Inject Sensor Disconnect
                </button>

                <button
                  type="button"
                  data-testid="btn-restore-sensor"
                  onClick={() => void handleRestoreSensor()}
                  className="w-full py-2.5 px-4 rounded-lg font-semibold text-xs flex items-center justify-center gap-2 bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/50 text-emerald-300 transition"
                >
                  <RefreshCw className="w-4 h-4" />
                  Restore Sensor &amp; Reset Fault
                </button>

                <button
                  type="button"
                  data-testid="btn-inject-spike"
                  onClick={() => void handleInjectSpike()}
                  className="w-full py-2 px-4 rounded-lg font-medium text-xs flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-amber-300 transition"
                >
                  <Play className="w-3.5 h-3.5" />
                  Inject +24% Single-Sample Spike
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
            <div className="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-sm font-bold text-slate-100">
                    Annotated Vector Pinout &amp; Orthogonal Wiring Diagram
                  </h2>
                  <p className="text-xs text-slate-400">
                    Board: {bp?.board.name} ({bp?.board.mcu})
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    data-testid="btn-zoom-out"
                    onClick={() => setSvgZoom((z) => Math.max(0.6, Number((z - 0.15).toFixed(2))))}
                    className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700"
                  >
                    <ZoomOut className="w-4 h-4" />
                  </button>
                  <span className="text-xs font-mono px-2">{Math.round(svgZoom * 100)}%</span>
                  <button
                    type="button"
                    data-testid="btn-zoom-in"
                    onClick={() => setSvgZoom((z) => Math.min(2.0, Number((z + 0.15).toFixed(2))))}
                    className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700"
                  >
                    <ZoomIn className="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    data-testid="btn-export-bundle"
                    onClick={() => void handleExportBundle()}
                    className="ml-2 flex items-center gap-1.5 px-3 py-1.5 rounded bg-cyan-500/20 hover:bg-cyan-500/30 border border-cyan-500/50 text-xs font-semibold text-cyan-300"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Export PlatformIO + BOM
                  </button>
                </div>
              </div>

              <div
                data-testid="svg-viewport"
                className="overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-2 max-h-[620px]"
              >
                {bp?.svg_diagram ? (
                  <div
                    style={{ transform: `scale(${svgZoom})`, transformOrigin: "top left" }}
                    dangerouslySetInnerHTML={{ __html: bp.svg_diagram }}
                  />
                ) : null}
              </div>
            </div>

            <div className="lg:col-span-5 flex flex-col gap-4">
              <div
                data-testid="drc-checklist"
                className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-bold text-slate-100">
                    Electrical Design Rule Check (DRC)
                  </span>
                  <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/50 flex items-center gap-1">
                    <CheckCircle2 className="w-3.5 h-3.5" />0 Critical Errors
                  </span>
                </div>

                {data?.initial_drc && data.initial_drc.error_count > 0 && (
                  <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 p-3 space-y-1.5">
                    <div className="text-xs font-bold text-amber-300">
                      Caught &amp; Auto-Repaired {data.initial_drc.error_count} Initial Hardware Fault(s):
                    </div>
                    {data.initial_drc.violations
                      .filter((v) => v.severity === "error")
                      .map((v, i) => (
                        <div key={i} className="text-[11px] text-slate-300 flex gap-2">
                          <span className="font-mono text-amber-400 shrink-0">[{v.rule_id}]</span>
                          <span>{v.message}</span>
                        </div>
                      ))}
                  </div>
                )}

                {bp?.drc.violations.map((v, i) => (
                  <div
                    key={i}
                    className="rounded-lg bg-slate-800/70 border border-slate-700 p-2.5 text-xs text-slate-300"
                  >
                    <span className="font-mono text-amber-300 font-semibold mr-2">
                      [{v.severity.toUpperCase()}: {v.rule_id}]
                    </span>
                    {v.message}
                  </div>
                ))}
              </div>

              {bp && (
                <div
                  data-testid="power-gauge"
                  className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold text-slate-100 flex items-center gap-2">
                      <BatteryCharging className="w-4 h-4 text-emerald-400" />
                      Power &amp; Battery Runtime Budget
                    </span>
                    {bp.power_budget.estimated_runtime_hours !== null && (
                      <span className="text-xs font-mono font-bold text-emerald-400">
                        Est. Runtime: {bp.power_budget.estimated_runtime_hours} h
                      </span>
                    )}
                  </div>

                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div className="bg-slate-950 rounded-lg p-2 border border-slate-800">
                      <div className="text-[10px] text-slate-400 uppercase">Idle</div>
                      <div className="font-mono font-bold text-xs text-slate-200">
                        {bp.power_budget.idle_current_ma} mA
                      </div>
                    </div>
                    <div className="bg-slate-950 rounded-lg p-2 border border-slate-800">
                      <div className="text-[10px] text-slate-400 uppercase">Average</div>
                      <div className="font-mono font-bold text-xs text-cyan-300">
                        {bp.power_budget.average_current_ma} mA ({bp.power_budget.average_power_w}W)
                      </div>
                    </div>
                    <div className="bg-slate-950 rounded-lg p-2 border border-slate-800">
                      <div className="text-[10px] text-slate-400 uppercase">Peak Burst</div>
                      <div className="font-mono font-bold text-xs text-amber-300">
                        {bp.power_budget.peak_current_ma} mA ({bp.power_budget.peak_power_w}W)
                      </div>
                    </div>
                  </div>

                  <div>
                    <div className="flex justify-between text-[11px] text-slate-400 mb-1">
                      <span>MCU Onboard Regulator Load</span>
                      <span className="font-mono">
                        {bp.power_budget.mcu_regulator_current_ma} / {bp.power_budget.mcu_regulator_limit_ma} mA
                      </span>
                    </div>
                    <div className="w-full h-2.5 bg-slate-800 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-emerald-400 rounded-full"
                        style={{
                          width: `${Math.min(
                            100,
                            (bp.power_budget.mcu_regulator_current_ma /
                              bp.power_budget.mcu_regulator_limit_ma) *
                              100
                          )}%`,
                        }}
                      />
                    </div>
                  </div>
                </div>
              )}

              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-2">
                <div className="text-xs font-bold text-slate-200">
                  Generated `platformio.ini` &amp; BOM ({bp?.bom.length ?? 0} items)
                </div>
                <pre className="text-[11px] font-mono bg-slate-950 border border-slate-800 rounded-lg p-3 overflow-x-auto text-cyan-300 max-h-44">
                  {data?.platformio_ini}
                </pre>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
