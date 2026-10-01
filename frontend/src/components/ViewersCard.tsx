import { useT } from "../hooks/useT";
import type { FaceInfo } from "../protocol/types";
import { useEos } from "../store";

const ORDER = { looking: 0, away: 1, ignored: 2 } as const;

function Viewer({ face }: { face: FaceInfo }) {
  const t = useT();
  const words = t.viewers;
  if (face.state === "ignored") {
    return (
      <li>
        <span className="chip state-absent">{words.ignored}</span>
        <span className="viewer-angles">{words.ignoredWhy}</span>
        <span />
      </li>
    );
  }
  const angles =
    face.yaw === null || face.pitch === null
      ? words.turnedAway
      : words.angles(t.fmt.signed(face.yaw), t.fmt.signed(face.pitch));
  return (
    <li>
      <span className={`chip state-${face.state}`}>{face.state === "looking" ? words.looking : words.away}</span>
      <span className="viewer-angles">{angles}</span>
      {face.eyes_down !== null ? (
        <span className="eyes" title={words.eyesDownTitle}>
          {words.eyesDown}
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
  const t = useT();
  const sorted = faces ? [...faces].sort((a, b) => ORDER[a.state] - ORDER[b.state]) : [];

  return (
    <div className="card">
      <div className="card-head">
        <h2>{t.viewers.title}</h2>
        <span className="muted">{room?.viewers ? t.viewers.inZone(room.viewers, room.looking) : ""}</span>
      </div>
      <ul className="viewers">
        {sorted.length ? (
          sorted.map((face) => <Viewer key={face.box.join(",")} face={face} />)
        ) : (
          <li className="empty">{t.viewers.nobody}</li>
        )}
      </ul>
    </div>
  );
}
