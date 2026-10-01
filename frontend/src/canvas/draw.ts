/** Shared canvas helpers: HiDPI sizing, rounded rectangles, label chips, colours. */

export const COLORS = {
  looking: "#3ecf8e",
  away: "#f5a524",
  absent: "#8b95a7",
  ignored: "#8b95a7",
  accent: "#7c8cff",
} as const;

export interface Sized {
  ctx: CanvasRenderingContext2D;
  width: number;
  height: number;
}

/** Matches the backing store to the element's CSS size and device pixel ratio, then clears. */
export function prepare(canvas: HTMLCanvasElement): Sized | null {
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return { ctx, width, height };
}

export function roundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

/** A small filled label; `anchor` says whether (x, y) is its top or bottom edge. */
export function chip(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  background: string,
  color: string,
  anchor: "top" | "bottom",
): void {
  ctx.font = "600 11.5px 'Segoe UI Variable Text', 'Segoe UI', system-ui, sans-serif";
  const width = ctx.measureText(text).width + 14;
  const height = 20;
  const top = anchor === "bottom" ? y - height : y;
  ctx.fillStyle = background;
  roundedRect(ctx, x, top, width, height, 6);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.textBaseline = "middle";
  ctx.fillText(text, x + 7, top + height / 2 + 0.5);
}
