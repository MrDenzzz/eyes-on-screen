import type { Attention } from "../protocol/types";

export interface TimelinePoint {
  ts: number;
  attention: Attention;
}

export interface Run {
  attention: Attention;
  start: number;
  end: number;
}

/** Frames further apart than this mean the video stalled: that stretch stays empty. */
export const MAX_GAP_MS = 1500;
const GAP_TAIL_MS = 100;

/**
 * Merges per-frame points into runs of equal attention. Drawing one rectangle per run
 * avoids the stripes that overlapping per-frame rectangles would show.
 */
export function toRuns(points: readonly TimelinePoint[], now: number): Run[] {
  const runs: Run[] = [];
  let run: Run | null = null;
  for (let index = 0; index < points.length; index++) {
    const point = points[index]!;
    const next = points[index + 1]?.ts ?? now;
    if (run && run.attention !== point.attention) {
      runs.push({ ...run, end: point.ts });
      run = null;
    }
    run ??= { attention: point.attention, start: point.ts, end: point.ts };
    if (next - point.ts > MAX_GAP_MS) {
      runs.push({ ...run, end: point.ts + GAP_TAIL_MS });
      run = null;
    }
  }
  if (run) runs.push({ ...run, end: now });
  return runs;
}
