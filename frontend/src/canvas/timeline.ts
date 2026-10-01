import type { Run } from "../lib/timeline";
import type { Marker } from "../store";
import { COLORS, prepare, roundedRect } from "./draw";

const BAR_TOP = 16;
const BAR_HEIGHT = 22;

/** The last `spanMs` of attention as coloured runs, with pause/resume markers and ticks. */
export function drawTimeline(
  canvas: HTMLCanvasElement,
  runs: readonly Run[],
  markers: readonly Marker[],
  now: number,
  spanMs: number,
): void {
  const sized = prepare(canvas);
  if (!sized) return;
  const { ctx, width } = sized;
  const start = now - spanMs;
  const x = (ts: number) => ((ts - start) / spanMs) * width;

  ctx.fillStyle = "rgba(255, 255, 255, 0.04)";
  roundedRect(ctx, 0, BAR_TOP, width, BAR_HEIGHT, 6);
  ctx.fill();

  ctx.save();
  roundedRect(ctx, 0, BAR_TOP, width, BAR_HEIGHT, 6);
  ctx.clip();
  for (const run of runs) {
    ctx.fillStyle = COLORS[run.attention];
    ctx.globalAlpha = run.attention === "absent" ? 0.4 : 0.95;
    ctx.fillRect(x(run.start), BAR_TOP, Math.max(1, x(run.end) - x(run.start)), BAR_HEIGHT);
  }
  ctx.restore();

  for (const marker of markers) {
    if (marker.ts < start) continue;
    const mx = x(marker.ts);
    ctx.fillStyle = marker.kind === "pause" ? COLORS.away : COLORS.looking;
    ctx.fillRect(mx - 1, BAR_TOP - 4, 2, BAR_HEIGHT + 8);
    ctx.beginPath();
    ctx.arc(mx, BAR_TOP - 7, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.fillStyle = "#5b6375";
  ctx.font = "11px 'Cascadia Mono', ui-monospace, monospace";
  ctx.textBaseline = "top";
  const spanS = spanMs / 1000;
  for (let s = 0; s <= spanS; s += 10) {
    const label = s === 0 ? "now" : `-${s}s`;
    const textWidth = ctx.measureText(label).width;
    const tx = width - (s / spanS) * width - textWidth / 2;
    ctx.fillText(label, Math.min(Math.max(tx, 0), width - textWidth), BAR_TOP + BAR_HEIGHT + 6);
  }
}
