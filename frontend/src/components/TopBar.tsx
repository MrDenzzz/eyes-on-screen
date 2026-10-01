import { useState } from "react";

import { api } from "../api";
import { run } from "../eos";
import type { Page } from "../hooks/usePage";
import { useT } from "../hooks/useT";
import { LANGS } from "../i18n";
import { setLang, useEos } from "../store";
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

function LanguageSwitch() {
  const lang = useEos((state) => state.lang);
  const t = useT();
  return (
    <div className="lang" role="radiogroup" aria-label={t.nav.language}>
      {LANGS.map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={option === lang}
          className={option === lang ? "on" : ""}
          onClick={() => setLang(option)}
        >
          {option.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

export function TopBar({ page }: { page: Page }) {
  const status = useEos((state) => state.status);
  const t = useT();
  // While a toggle is in flight, show what the user chose rather than the old status.
  const [pending, setPending] = useState<boolean | null>(null);

  const stream = status?.stream;
  const player = status?.player;
  const subtitle = !status
    ? t.top.connecting
    : stream?.connected
      ? t.top.stream(stream.width ?? 0, stream.height ?? 0, status.analysis.fps.toFixed(1), Math.round(status.analysis.ms))
      : (stream?.error ?? t.top.waitingCamera);
  const automation = pending ?? status?.automation.enabled ?? true;

  async function toggle(enabled: boolean) {
    setPending(enabled);
    await run(api.setAutomation(enabled), t.top.automation);
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
      <nav className="tabs" aria-label={t.nav.pages}>
        <a href="#" className={page === "live" ? "on" : ""} aria-current={page === "live" ? "page" : undefined}>
          {t.nav.live}
        </a>
        <a href="#record" className={page === "record" ? "on" : ""} aria-current={page === "record" ? "page" : undefined}>
          {t.nav.record}
        </a>
      </nav>
      <div className="topbar-right">
        <Pill
          label={t.top.camera}
          level={!status ? "warn" : stream?.connected ? "ok" : "warn"}
          value={!status ? "–" : stream?.connected ? t.top.fps(Math.round(stream.fps)) : t.top.reconnecting}
        />
        <Pill
          label={t.top.appleTv}
          level={!status ? "warn" : player?.connected ? "ok" : player?.configured ? "bad" : "warn"}
          value={
            !status
              ? "–"
              : player?.connected
                ? (player.name ?? t.top.connected)
                : player?.configured
                  ? t.top.offline
                  : t.top.notSetUp
          }
        />
        {status?.automation.dry_run && <span className="badge badge-warn">{t.top.dryRun}</span>}
        <label className="switch" title={t.top.automationTitle}>
          <input
            type="checkbox"
            checked={automation}
            disabled={!status}
            onChange={(event) => void toggle(event.target.checked)}
          />
          <span className="track">
            <span className="thumb" />
          </span>
          <span>{t.top.automation}</span>
        </label>
        <LanguageSwitch />
      </div>
    </header>
  );
}
