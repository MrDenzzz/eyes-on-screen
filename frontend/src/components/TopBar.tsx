import { useState } from "react";

import { api } from "../api";
import { run } from "../eos";
import { useEos } from "../store";
import { Logo } from "./icons";

type Level = "ok" | "warn" | "bad";

function Pill({ label, level, value }: { label: string; level: Level; value: string }) {
  return (
    <span className={`pill ${level}`}>
      <i className="dot" />
      {label} <b>{value}</b>
    </span>
  );
}

export function TopBar() {
  const status = useEos((state) => state.status);
  // While a toggle is in flight, show what the user chose rather than the old status.
  const [pending, setPending] = useState<boolean | null>(null);

  const stream = status?.stream;
  const player = status?.player;
  const subtitle = !status
    ? "connecting…"
    : stream?.connected
      ? `${stream.width}×${stream.height} · ${status.analysis.fps.toFixed(1)} fps analysed · ${Math.round(status.analysis.ms)} ms`
      : (stream?.error ?? "waiting for the camera");
  const automation = pending ?? status?.automation.enabled ?? true;

  async function toggle(enabled: boolean) {
    setPending(enabled);
    await run(api.setAutomation(enabled), "Automation");
    setPending(null);
  }

  return (
    <header className="topbar">
      <div className="brand">
        <Logo />
        <div>
          <div className="brand-name">eyes-on-screen</div>
          <div className="brand-sub">{subtitle}</div>
        </div>
      </div>
      <div className="topbar-right">
        <Pill
          label="Camera"
          level={!status ? "warn" : stream?.connected ? "ok" : "warn"}
          value={!status ? "–" : stream?.connected ? `${Math.round(stream.fps)} fps` : "reconnecting"}
        />
        <Pill
          label="Apple TV"
          level={!status ? "warn" : player?.connected ? "ok" : "bad"}
          value={!status ? "–" : player?.connected ? (player.name ?? "connected") : "offline"}
        />
        {status?.automation.dry_run && <span className="badge badge-warn">Dry run</span>}
        <label className="switch" title="When off, nothing is paused or resumed">
          <input
            type="checkbox"
            checked={automation}
            disabled={!status}
            onChange={(event) => void toggle(event.target.checked)}
          />
          <span className="track">
            <span className="thumb" />
          </span>
          <span>Automation</span>
        </label>
      </div>
    </header>
  );
}
