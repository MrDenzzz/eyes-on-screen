import { type PointerEvent, useLayoutEffect, useRef, useState } from "react";

import { drawVideo, type Roi, toFramePoint, type Viewport } from "../canvas/video";
import { api } from "../api";
import { run } from "../eos";
import { useResizeTick } from "../hooks/useResizeTick";
import { describeNow } from "../lib/now";
import type { CalibrationInfo, StatusMessage } from "../protocol/types";
import { setZoneEditing, useEos } from "../store";
import { FullscreenIcon, TargetIcon, ZoneIcon } from "./icons";

const STATE_LABEL = { looking: "LOOKING", away: "AWAY", absent: "NOBODY" } as const;
const MIN_ZONE = 0.03;
const RING_LENGTH = 327; // circumference of the r=52 calibration ring

export function VideoStage() {
  const frame = useEos((state) => state.frame);
  const status = useEos((state) => state.status);
  const editing = useEos((state) => state.zoneEditing);
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewport = useRef<Viewport | null>(null);
  const [draft, setDraft] = useState<Roi | null>(null);
  const [dragStart, setDragStart] = useState<[number, number] | null>(null);
  const resizeTick = useResizeTick(wrapRef);

  const savedRoi = status ? (status.settings.roi as Roi) : null;
  const roi = editing ? (draft ?? savedRoi) : savedRoi;

  useLayoutEffect(() => {
    if (canvasRef.current) viewport.current = drawVideo(canvasRef.current, frame, roi, editing);
  }, [frame, roi, editing, resizeTick]);

  function stopEditing() {
    setZoneEditing(false);
    setDraft(null);
    setDragStart(null);
  }

  function pointAt(event: PointerEvent<HTMLCanvasElement>): [number, number] | null {
    return viewport.current
      ? toFramePoint(viewport.current, event.nativeEvent.offsetX, event.nativeEvent.offsetY)
      : null;
  }

  function onPointerDown(event: PointerEvent<HTMLCanvasElement>) {
    if (!editing) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragStart(pointAt(event));
  }

  function onPointerMove(event: PointerEvent<HTMLCanvasElement>) {
    const point = editing && dragStart ? pointAt(event) : null;
    if (!point || !dragStart) return;
    const [ax, ay] = dragStart;
    const [bx, by] = point;
    setDraft([Math.min(ax, bx), Math.min(ay, by), Math.max(ax, bx), Math.max(ay, by)]);
  }

  async function saveZone() {
    if (!draft) return;
    const rounded = draft.map((value) => Math.round(value * 1000) / 1000) as Roi;
    if (await run(api.changeSettings({ target: { roi: rounded } }), "Zone not saved")) {
      stopEditing();
    }
  }

  const draftValid = draft !== null && draft[2] - draft[0] >= MIN_ZONE && draft[3] - draft[1] >= MIN_ZONE;

  return (
    <div className="card stage">
      <div ref={wrapRef} className={`video-wrap${editing ? " editing" : ""}`}>
        <canvas
          ref={canvasRef}
          id="video"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={() => setDragStart(null)}
        />
        {!frame && (
          <div className="video-empty">
            <div className="spinner" />
            <span>{status && !status.stream.connected ? "Waiting for the camera…" : "Waiting for video…"}</span>
          </div>
        )}

        <div className="toolbar">
          <button
            type="button"
            className={`tool${editing ? " active" : ""}`}
            title="Draw the area where viewers sit"
            onClick={() => (editing ? stopEditing() : setZoneEditing(true))}
          >
            <ZoneIcon />
            Zone
          </button>
          <button
            type="button"
            className={`tool${status?.calibration ? " active" : ""}`}
            title="Look at the screen to set what counts as watching"
            onClick={() => void run(api.calibrate(), "Calibration")}
          >
            <TargetIcon />
            Calibrate
          </button>
          <button
            type="button"
            className="tool tool-icon"
            title="Full screen"
            onClick={() =>
              document.fullscreenElement ? void document.exitFullscreen() : void wrapRef.current?.requestFullscreen()
            }
          >
            <FullscreenIcon />
          </button>
        </div>

        {editing && (
          <div className="zone-bar">
            <span>Drag across the video to draw the viewing zone</span>
            <button type="button" className="btn btn-primary" disabled={!draftValid} onClick={() => void saveZone()}>
              Save
            </button>
            <button type="button" className="btn" onClick={stopEditing}>
              Cancel
            </button>
          </div>
        )}

        {status && <NowBadge status={status} />}
        {status?.calibration && <CalibrationOverlay calibration={status.calibration} />}
      </div>
    </div>
  );
}

function NowBadge({ status }: { status: StatusMessage }) {
  const now = describeNow(status);
  return (
    <div className={`now state-${now.attention}`}>
      <div className="now-row">
        <span className="now-state">{STATE_LABEL[now.attention]}</span>
        <span className="now-detail">{now.detail}</span>
      </div>
      <div className="now-progress">
        <div className="now-bar" style={{ width: `${Math.round(now.progress * 100)}%` }} />
      </div>
    </div>
  );
}

function CalibrationOverlay({ calibration }: { calibration: CalibrationInfo }) {
  const counting = calibration.phase === "countdown";
  const done = Math.min(1, Math.max(0, 1 - calibration.remaining_s / calibration.phase_s));
  return (
    <div className="calib">
      <div className="calib-ring">
        <svg viewBox="0 0 120 120" aria-hidden="true">
          <circle cx="60" cy="60" r="52" className="calib-track" />
          <circle cx="60" cy="60" r="52" className="calib-arc" style={{ strokeDashoffset: RING_LENGTH * (1 - done) }} />
        </svg>
        <span>{counting ? Math.ceil(calibration.remaining_s) : "●"}</span>
      </div>
      <div className="calib-text">{counting ? "Look at the screen" : "Hold still…"}</div>
    </div>
  );
}
