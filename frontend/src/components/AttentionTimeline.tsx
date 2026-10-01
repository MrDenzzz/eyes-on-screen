import { useLayoutEffect, useMemo, useRef } from "react";

import { drawTimeline } from "../canvas/timeline";
import { useResizeTick } from "../hooks/useResizeTick";
import { toRuns } from "../lib/timeline";
import { TIMELINE_MS, useEos } from "../store";

export function AttentionTimeline() {
  const timeline = useEos((state) => state.timeline);
  const markers = useEos((state) => state.markers);
  const now = useEos((state) => state.frame?.header.ts ?? null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const resizeTick = useResizeTick(canvasRef);
  const end = now ?? Date.now();
  const runs = useMemo(() => toRuns(timeline, end), [timeline, end]);

  useLayoutEffect(() => {
    if (canvasRef.current) drawTimeline(canvasRef.current, runs, markers, end, TIMELINE_MS);
  }, [runs, markers, end, resizeTick]);

  return (
    <div className="card">
      <div className="card-head">
        <h2>Attention</h2>
        <span className="muted">last 60 seconds</span>
        <div className="legend">
          <span>
            <i className="sw sw-looking" />
            Looking
          </span>
          <span>
            <i className="sw sw-away" />
            Away
          </span>
          <span>
            <i className="sw sw-absent" />
            Nobody
          </span>
        </div>
      </div>
      <canvas ref={canvasRef} className="timeline" />
    </div>
  );
}
