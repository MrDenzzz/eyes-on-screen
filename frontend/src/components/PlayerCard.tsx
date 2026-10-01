import { api } from "../api";
import { run } from "../eos";
import { useEos } from "../store";
import { PauseIcon, PlayIcon } from "./icons";

export function PlayerCard() {
  const player = useEos((state) => state.status?.player ?? null);
  const machine = useEos((state) => state.status?.machine ?? null);
  const connected = player?.connected ?? false;
  const playback = player?.playback ?? null;

  return (
    <div className="card">
      <div className="card-head">
        <h2>Player</h2>
        <span className="muted">{player?.name ?? ""}</span>
      </div>
      <div className="player">
        <div className="player-state">
          {!player ? "–" : !player.configured ? "Not set up" : connected ? (playback ?? "unknown") : "offline"}
        </div>
        <div className="player-title">
          {player?.title ??
            (!player
              ? "Nothing reported yet"
              : !player.configured
                ? "Watching only: pair an Apple TV with `eos atv pair`"
                : connected
                  ? "Nothing playing"
                  : "Apple TV not connected")}
        </div>
        <div className="player-app">{player?.app ?? ""}</div>
        <div className="player-badges">
          {playback === "paused" &&
            (machine?.paused_by_us ? (
              <span className="badge badge-accent">Paused by eos</span>
            ) : (
              <span className="badge">Paused from the remote</span>
            ))}
          {playback === "playing" && machine && !machine.armed && (
            <span className="badge badge-warn">Waiting for a look</span>
          )}
        </div>
        <div className="player-actions">
          <button
            type="button"
            className="btn"
            disabled={!connected || playback !== "playing"}
            onClick={() => void run(api.press("pause"), "Pause")}
          >
            <PauseIcon />
            Pause
          </button>
          <button
            type="button"
            className="btn"
            disabled={!connected || playback !== "paused"}
            onClick={() => void run(api.press("play"), "Play")}
          >
            <PlayIcon />
            Play
          </button>
        </div>
      </div>
    </div>
  );
}
