import { api } from "../api";
import { run } from "../eos";
import { useT } from "../hooks/useT";
import { useEos } from "../store";
import { PauseIcon, PlayIcon } from "./icons";

export function PlayerCard() {
  const player = useEos((state) => state.status?.player ?? null);
  const machine = useEos((state) => state.status?.machine ?? null);
  const t = useT();
  const words = t.player;
  const connected = player?.connected ?? false;
  const playback = player?.playback ?? null;

  const state = !player
    ? "–"
    : !player.configured
      ? words.notSetUp
      : connected
        ? t.playback[playback ?? "unknown"]
        : words.offline;
  const title =
    player?.title ??
    (!player
      ? words.nothingYet
      : !player.configured
        ? words.watchOnly
        : connected
          ? words.nothingPlaying
          : words.notConnected);

  return (
    <div className="card">
      <div className="card-head">
        <h2>{words.title}</h2>
        <span className="muted">{player?.name ?? ""}</span>
      </div>
      <div className="player">
        <div className="player-state">{state}</div>
        <div className="player-title">{title}</div>
        <div className="player-app">{player?.app ?? ""}</div>
        <div className="player-badges">
          {playback === "paused" &&
            (machine?.paused_by_us ? (
              <span className="badge badge-accent">{words.pausedByEos}</span>
            ) : (
              <span className="badge">{words.pausedRemote}</span>
            ))}
          {playback === "playing" && machine && !machine.armed && (
            <span className="badge badge-warn">{words.waitingLook}</span>
          )}
        </div>
        <div className="player-actions">
          <button
            type="button"
            className="btn"
            disabled={!connected || playback !== "playing"}
            onClick={() => void run(api.press("pause"), words.pause)}
          >
            <PauseIcon />
            {words.pause}
          </button>
          <button
            type="button"
            className="btn"
            disabled={!connected || playback !== "paused"}
            onClick={() => void run(api.press("play"), words.play)}
          >
            <PlayIcon />
            {words.play}
          </button>
        </div>
      </div>
    </div>
  );
}
