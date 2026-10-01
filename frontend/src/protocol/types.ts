/* Generated from src/protocol/schema.json (eyes_on_screen/web/messages.py). Do not edit: run npm run gen. */

/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "Attention".
 */
export type Attention = "looking" | "away" | "absent";
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "MultipleViewers".
 */
export type MultipleViewers = "any_away" | "all_away" | "nearest";
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "FaceLostAction".
 */
export type FaceLostAction = "pause" | "ignore";
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "PlaybackCommand".
 */
export type PlaybackCommand = "pause" | "resume";
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "Playback".
 */
export type Playback = "playing" | "paused" | "idle" | "loading" | "stopped" | "seeking" | "unknown";

export interface Protocol {}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "AnalysisInfo".
 */
export interface AnalysisInfo {
  fps: number;
  ms: number;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "AutomationInfo".
 */
export interface AutomationInfo {
  enabled: boolean;
  dry_run: boolean;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "AutomationUpdate".
 */
export interface AutomationUpdate {
  enabled: boolean;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "BehaviorChanges".
 */
export interface BehaviorChanges {
  face_lost_after_s?: number | null;
  multiple_viewers?: MultipleViewers | null;
  on_face_lost?: FaceLostAction | null;
  pause_after_s?: number | null;
  resume_after_s?: number | null;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "BehaviorConfig".
 */
export interface BehaviorConfig {
  pause_after_s: number;
  resume_after_s: number;
  on_face_lost: FaceLostAction;
  face_lost_after_s: number;
  multiple_viewers: MultipleViewers;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "CalibrationInfo".
 */
export interface CalibrationInfo {
  phase: "countdown" | "collecting";
  remaining_s: number;
  phase_s: number;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "EventInfo".
 */
export interface EventInfo {
  ts: number;
  time: string;
  level: "info" | "warning";
  kind: "pause" | "resume" | "player" | "calibration" | "other";
  text: string;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "EventsMessage".
 */
export interface EventsMessage {
  type: "events";
  events: EventInfo[];
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "FaceInfo".
 */
export interface FaceInfo {
  /**
   * @minItems 4
   * @maxItems 4
   */
  box: [number, number, number, number];
  state: "looking" | "away" | "ignored";
  yaw: number | null;
  pitch: number | null;
  eyes_down: number | null;
  focus: boolean;
}
/**
 * JSON header of a binary frame message; the JPEG follows it.
 *
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "FrameHeader".
 */
export interface FrameHeader {
  seq: number;
  ts: number;
  attention: Attention;
  faces: FaceInfo[];
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "MachineInfo".
 */
export interface MachineInfo {
  streak_s: number;
  paused_by_us: boolean;
  armed: boolean;
  pending: PlaybackCommand | null;
  skipped: PlaybackCommand | null;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "PlayerInfo".
 */
export interface PlayerInfo {
  connected: boolean;
  name: string | null;
  playback: Playback | null;
  app: string | null;
  title: string | null;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "PoseChanges".
 */
export interface PoseChanges {
  pitch_center_deg?: number | null;
  pitch_tolerance_deg?: number | null;
  yaw_center_deg?: number | null;
  yaw_tolerance_deg?: number | null;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "PoseConfig".
 */
export interface PoseConfig {
  yaw_center_deg: number;
  pitch_center_deg: number;
  yaw_tolerance_deg: number;
  pitch_tolerance_deg: number;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "RecordingInfo".
 */
export interface RecordingInfo {
  file: string;
  current: RecordingProgress | null;
  done: RecordingResult[];
  last: number | null;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "RecordingProgress".
 */
export interface RecordingProgress {
  index: number;
  phase: "countdown" | "recording";
  remaining_s: number;
  phase_s: number;
  frames: number;
  with_face: number;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "RecordingResult".
 */
export interface RecordingResult {
  index: number;
  take: number;
  frames: number;
  with_face: number;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "RecordingStepInfo".
 */
export interface RecordingStepInfo {
  label: string;
  title: string;
  instruction: string;
  duration_s: number;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "RoomInfo".
 */
export interface RoomInfo {
  attention: Attention;
  viewers: number;
  looking: number;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "SettingsChanges".
 */
export interface SettingsChanges {
  target?: TargetChanges | null;
  pose?: PoseChanges | null;
  behavior?: BehaviorChanges | null;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "TargetChanges".
 */
export interface TargetChanges {
  roi?: [number, number, number, number] | null;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "SettingsInfo".
 */
export interface SettingsInfo {
  /**
   * @minItems 4
   * @maxItems 4
   */
  roi: [number, number, number, number];
  pose: PoseConfig;
  behavior: BehaviorConfig;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "StatusMessage".
 */
export interface StatusMessage {
  type: "status";
  stream: StreamInfo;
  analysis: AnalysisInfo;
  player: PlayerInfo;
  room: RoomInfo;
  machine: MachineInfo;
  automation: AutomationInfo;
  calibration: CalibrationInfo | null;
  recording: RecordingInfo | null;
  settings: SettingsInfo;
}
/**
 * This interface was referenced by `Protocol`'s JSON-Schema
 * via the `definition` "StreamInfo".
 */
export interface StreamInfo {
  connected: boolean;
  width: number | null;
  height: number | null;
  fps: number;
  error: string | null;
}
