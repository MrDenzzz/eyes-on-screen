import { signed } from "../lib/format";
import type { FaceInfo } from "../protocol/types";
import { useEos } from "../store";

const ORDER = { looking: 0, away: 1, ignored: 2 } as const;
const LABEL = { looking: "Looking", away: "Away" } as const;

function Viewer({ face }: { face: FaceInfo }) {
  if (face.state === "ignored") {
    return (
      <li>
        <span className="chip state-absent">Ignored</span>
        <span className="viewer-angles">face-like print, never had landmarks</span>
        <span />
      </li>
    );
  }
  const angles =
    face.yaw === null || face.pitch === null
      ? "turned away, no landmarks"
      : `yaw ${signed(face.yaw)}° · pitch ${signed(face.pitch)}°`;
  return (
    <li>
      <span className={`chip state-${face.state}`}>{LABEL[face.state]}</span>
      <span className="viewer-angles">{angles}</span>
      {face.eyes_down !== null ? (
        <span className="eyes" title="Eyes looking down">
          eyes ↓
          <span className="eyes-meter">
            <i style={{ width: `${Math.round(face.eyes_down * 100)}%` }} />
          </span>
        </span>
      ) : (
        <span />
      )}
    </li>
  );
}

export function ViewersCard() {
  const faces = useEos((state) => state.frame?.header.faces ?? null);
  const room = useEos((state) => state.status?.room ?? null);
  const sorted = faces ? [...faces].sort((a, b) => ORDER[a.state] - ORDER[b.state]) : [];

  return (
    <div className="card">
      <div className="card-head">
        <h2>Viewers</h2>
        <span className="muted">{room?.viewers ? `${room.viewers} in the zone · ${room.looking} looking` : ""}</span>
      </div>
      <ul className="viewers">
        {sorted.length ? (
          sorted.map((face) => <Viewer key={face.box.join(",")} face={face} />)
        ) : (
          <li className="empty">Nobody in the zone</li>
        )}
      </ul>
    </div>
  );
}
