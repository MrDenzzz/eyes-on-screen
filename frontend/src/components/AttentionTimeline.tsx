import { useLayoutEffect, useMemo, useRef } from "react";

import { drawTimeline } from "../canvas/timeline";
import { useResizeTick } from "../hooks/useResizeTick";
import { useT } from "../hooks/useT";
import { toRuns } from "../lib/timeline";
import { TIMELINE_MS, useEos } from "../store";

export function AttentionTimeline() {
  const timeline = useEos((state) => state.timeline);
  const markers = useEos((state) => state.markers);
  const now = useEos((state) => state.frame?.header.ts ?? null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const t = useT();
  const resizeTick = useResizeTick(canvasRef);
  const end = now ?? Date.now();
  const runs = useMemo(() => toRuns(timeline, end), [timeline, end]);

  useLayoutEffect(() => {
    if (canvasRef.current) drawTimeline(canvasRef.current, runs, markers, end, TIMELINE_MS, t.timeline);
  }, [runs, markers, end, resizeTick, t]);

  return (
    <div className="card">
      <div className="card-head">
        <h2>{t.timeline.title}</h2>
        <span className="muted">{t.timeline.span}</span>
        <div className="legend">
          <span>
            <i className="sw sw-looking" />
            {t.timeline.looking}
          </span>
          <span>
            <i className="sw sw-away" />
            {t.timeline.away}
          </span>
          <span>
            <i className="sw sw-absent" />
            {t.timeline.nobody}
          </span>
        </div>
      </div>
      <canvas ref={canvasRef} className="timeline" />
    </div>
  );
}
