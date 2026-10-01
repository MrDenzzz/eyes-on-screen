/** The first step without a finished take, or null once every step has one. */
export function nextStep(count: number, done: ReadonlyMap<number, unknown>): number | null {
  for (let index = 0; index < count; index++) if (!done.has(index)) return index;
  return null;
}

/** Share of frames where the face was measured, as "96%"; "–" before any frame. */
export function faceShare({ frames, with_face }: { frames: number; with_face: number }): string {
  return frames ? `${Math.round((100 * with_face) / frames)}%` : "–";
}

/** Seconds left as m:ss, rounded up so the clock never shows 0:00 too early. */
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}
