import type { StatusMessage } from "../protocol/types";

type DeepPartial<T> = { [K in keyof T]?: T[K] extends object ? DeepPartial<T[K]> : T[K] };

const BASE: StatusMessage = {
  type: "status",
  stream: { connected: true, width: 2560, height: 1440, fps: 20, error: null },
  analysis: { fps: 10, ms: 12 },
  player: { connected: true, name: "Living room", playback: "playing", app: "TV", title: "Show" },
  room: { attention: "looking", viewers: 1, looking: 1 },
  machine: { streak_s: 0, paused_by_us: false, armed: true, pending: null, skipped: null },
  automation: { enabled: true, dry_run: false },
  calibration: null,
  settings: {
    roi: [0.1, 0.3, 0.75, 0.65],
    pose: { yaw_center_deg: 2.9, pitch_center_deg: 3.6, yaw_tolerance_deg: 20, pitch_tolerance_deg: 15 },
    behavior: {
      pause_after_s: 1.5,
      resume_after_s: 0.5,
      on_face_lost: "pause",
      face_lost_after_s: 3,
      multiple_viewers: "any_away",
    },
  },
};

/** A full status message with selected parts overridden (one level deep per section). */
export function makeStatus(overrides: DeepPartial<StatusMessage> = {}): StatusMessage {
  const merged = structuredClone(BASE) as unknown as Record<string, unknown>;
  for (const [key, value] of Object.entries(overrides)) {
    const current = merged[key];
    merged[key] =
      value && typeof value === "object" && !Array.isArray(value) && current && typeof current === "object"
        ? { ...(current as object), ...(value as object) }
        : value;
  }
  return merged as unknown as StatusMessage;
}
