import { signed } from "../lib/format";
import type { FaceInfo } from "../protocol/types";
import type { Frame } from "../store";
import { COLORS, chip, prepare } from "./draw";

export type Roi = [number, number, number, number];

/** Where the video sits on the canvas (letterboxed), in CSS pixels. */
export interface Viewport {
  x: number;
  y: number;
  w: number;
  h: number;
}

const STATE_LABEL = { looking: "Looking", away: "Away" } as const;

/** Draws the frame, the viewing zone and every face; returns where the video landed. */
export function drawVideo(
  canvas: HTMLCanvasElement,
  frame: Frame | null,
  roi: Roi | null,
  editing: boolean,
): Viewport | null {
  const sized = prepare(canvas);
  if (!sized || !frame) return null;
  const { ctx, width, height } = sized;
  const { bitmap, header } = frame;
  const scale = Math.min(width / bitmap.width, height / bitmap.height);
  const view: Viewport = {
    x: (width - bitmap.width * scale) / 2,
    y: (height - bitmap.height * scale) / 2,
    w: bitmap.width * scale,
    h: bitmap.height * scale,
  };
  ctx.drawImage(bitmap, view.x, view.y, view.w, view.h);
  if (roi) drawZone(ctx, view, roi, editing);
  if (!editing) header.faces.forEach((face) => drawFace(ctx, view, face));
  return view;
}

function drawZone(ctx: CanvasRenderingContext2D, view: Viewport, roi: Roi, editing: boolean): void {
  const [x1, y1, x2, y2] = roi;
  const zone = { x: view.x + x1 * view.w, y: view.y + y1 * view.h, w: (x2 - x1) * view.w, h: (y2 - y1) * view.h };
  ctx.save();
  // Spotlight: dim everything outside the zone.
  ctx.fillStyle = editing ? "rgba(5, 7, 12, 0.66)" : "rgba(5, 7, 12, 0.5)";
  ctx.beginPath();
  ctx.rect(view.x, view.y, view.w, view.h);
  ctx.rect(zone.x, zone.y, zone.w, zone.h);
  ctx.fill("evenodd");
  ctx.setLineDash(editing ? [] : [7, 6]);
  ctx.lineWidth = editing ? 2 : 1.3;
  ctx.strokeStyle = editing ? COLORS.accent : "rgba(124, 140, 255, 0.75)";
  ctx.strokeRect(zone.x, zone.y, zone.w, zone.h);
  ctx.setLineDash([]);
  chip(ctx, "VIEWING ZONE", zone.x + 8, zone.y + 8, "rgba(124, 140, 255, 0.92)", "#fff", "top");
  if (editing) {
    ctx.fillStyle = COLORS.accent;
    for (const [hx, hy] of [
      [zone.x, zone.y],
      [zone.x + zone.w, zone.y],
      [zone.x, zone.y + zone.h],
      [zone.x + zone.w, zone.y + zone.h],
    ] as const) {
      ctx.beginPath();
      ctx.arc(hx, hy, 5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

function drawFace(ctx: CanvasRenderingContext2D, view: Viewport, face: FaceInfo): void {
  const [x1, y1, x2, y2] = face.box;
  const box = { x: view.x + x1 * view.w, y: view.y + y1 * view.h, w: (x2 - x1) * view.w, h: (y2 - y1) * view.h };
  ctx.save();

  if (face.state === "ignored") {
    // Face-like decor (the cat pillow): visible, but clearly not a viewer.
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(139, 149, 167, 0.7)";
    ctx.strokeRect(box.x, box.y, box.w, box.h);
    ctx.setLineDash([]);
    chip(ctx, "ignored", box.x, box.y - 6, "rgba(20, 23, 32, 0.85)", COLORS.ignored, "bottom");
    ctx.restore();
    return;
  }

  const color = COLORS[face.state];
  const pad = Math.max(4, box.w * 0.12);
  const frame = { x: box.x - pad, y: box.y - pad, w: box.w + 2 * pad, h: box.h + 2 * pad };
  const arm = Math.max(7, Math.min(frame.w, frame.h) * 0.28);
  ctx.strokeStyle = color;
  ctx.lineWidth = face.focus ? 3 : 2;
  ctx.lineCap = "round";
  ctx.shadowColor = "rgba(0, 0, 0, 0.5)";
  ctx.shadowBlur = 6;
  ctx.beginPath();
  // Viewfinder corners instead of a full box.
  for (const [cx, cy, dx, dy] of [
    [frame.x, frame.y, 1, 1],
    [frame.x + frame.w, frame.y, -1, 1],
    [frame.x, frame.y + frame.h, 1, -1],
    [frame.x + frame.w, frame.y + frame.h, -1, -1],
  ] as const) {
    ctx.moveTo(cx, cy + dy * arm);
    ctx.lineTo(cx, cy);
    ctx.lineTo(cx + dx * arm, cy);
  }
  ctx.stroke();
  ctx.shadowBlur = 0;

  if (face.yaw !== null && face.pitch !== null) {
    // Where the face points: right for +yaw, up for +pitch.
    const cx = box.x + box.w / 2;
    const cy = box.y + box.h / 2;
    const length = Math.max(26, box.w * 1.9);
    arrow(
      ctx,
      cx,
      cy,
      cx + length * Math.sin((face.yaw * Math.PI) / 180),
      cy - length * Math.sin((face.pitch * Math.PI) / 180),
      color,
    );
  }

  const angles =
    face.yaw === null || face.pitch === null ? "no landmarks" : `${signed(face.yaw)}° / ${signed(face.pitch)}°`;
  chip(ctx, `${STATE_LABEL[face.state]} · ${angles}`, frame.x, frame.y - 6, color, "#0b0d12", "bottom");
  ctx.restore();
}

function arrow(ctx: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number, color: string): void {
  const angle = Math.atan2(y2 - y1, x2 - x1);
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 2;
  ctx.globalAlpha = 0.9;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - 9 * Math.cos(angle - 0.45), y2 - 9 * Math.sin(angle - 0.45));
  ctx.lineTo(x2 - 9 * Math.cos(angle + 0.45), y2 - 9 * Math.sin(angle + 0.45));
  ctx.closePath();
  ctx.fill();
  ctx.globalAlpha = 1;
}

/** A pointer position as normalized frame coordinates, clamped to the video. */
export function toFramePoint(view: Viewport, offsetX: number, offsetY: number): [number, number] {
  const x = (offsetX - view.x) / view.w;
  const y = (offsetY - view.y) / view.h;
  return [Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))];
}
