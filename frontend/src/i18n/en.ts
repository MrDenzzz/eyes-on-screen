import { signed } from "../lib/format";
import type { EventInfo, Playback } from "../protocol/types";

type Params = EventInfo["params"];

const seconds = (value: number) => `${Math.max(0, value).toFixed(1)} s`;

const REASONS: Record<string, string> = {
  looked_away: "looked away for",
  no_viewer: "no viewer for",
  looking: "looking at the screen for",
};
const why = (p: Params) => `${REASONS[String(p.reason)] ?? p.reason} ${Number(p.seconds).toFixed(1)}s`;

const PLAYBACK: Record<Playback, string> = {
  playing: "playing",
  paused: "paused",
  idle: "idle",
  loading: "loading",
  stopped: "stopped",
  seeking: "seeking",
  unknown: "unknown",
};

/** The source dictionary: every other language has exactly this shape (see Dict). */
export const en = {
  fmt: {
    seconds,
    duration: (value: number) => `${value} s`,
    degrees: (value: number) => `±${value}°`,
    signed: (value: number, digits = 0) => signed(value, digits),
  },
  playback: PLAYBACK,
  nav: { pages: "Pages", live: "Live", record: "Record", language: "Language" },
  top: {
    connecting: "connecting…",
    waitingCamera: "waiting for the camera",
    stream: (width: number, height: number, fps: string, ms: number) =>
      `${width}×${height} · ${fps} fps analysed · ${ms} ms`,
    camera: "Camera",
    fps: (fps: number) => `${fps} fps`,
    reconnecting: "reconnecting",
    appleTv: "Apple TV",
    connected: "connected",
    offline: "offline",
    notSetUp: "not set up",
    dryRun: "Dry run",
    automation: "Automation",
    automationTitle: "When off, nothing is paused or resumed",
  },
  video: {
    waitingCamera: "Waiting for the camera…",
    waitingVideo: "Waiting for video…",
    zone: "Zone",
    zoneTitle: "Draw the area where viewers sit",
    calibrate: "Calibrate",
    calibrateTitle: "Look at the screen to set what counts as watching",
    fullscreen: "Full screen",
    zoneHint: "Drag across the video to draw the viewing zone",
    save: "Save",
    cancel: "Cancel",
    zoneNotSaved: "Zone not saved",
    calibration: "Calibration",
    lookAtScreen: "Look at the screen",
    holdStill: "Hold still…",
    state: { looking: "LOOKING", away: "AWAY", absent: "NOBODY" },
    viewingZone: "VIEWING ZONE",
    ignored: "ignored",
    noLandmarks: "no landmarks",
    face: { looking: "Looking", away: "Away" },
  },
  now: {
    automationOff: "automation is off",
    notConnected: "Apple TV not connected",
    pausingNow: "pausing…",
    resumingNow: "resuming…",
    skipped: (command: "pause" | "resume") =>
      `dry run · would ${command}, nothing sent`,
    pausing: "pausing",
    wouldPause: "would pause",
    resuming: "resuming",
    wouldResume: "would resume",
    countdown: (what: string, left: string) => `${what} in ${left}`,
    nobodyHere: (what: string) => `nobody here · ${what}`,
    pausedByEos: "paused by eos · look at the screen to resume",
    pausedRemote: "paused from the remote · left alone",
    waitingLook: "waiting for someone to look",
    watching: "watching",
    player: (playback: string) => `player ${playback}`,
  },
  timeline: {
    title: "Attention",
    span: "last 60 seconds",
    looking: "Looking",
    away: "Away",
    nobody: "Nobody",
    now: "now",
    ago: (s: number) => `-${s}s`,
  },
  player: {
    title: "Player",
    notSetUp: "Not set up",
    offline: "offline",
    nothingYet: "Nothing reported yet",
    watchOnly: "Watching only: pair an Apple TV with `eos atv pair`",
    nothingPlaying: "Nothing playing",
    notConnected: "Apple TV not connected",
    pausedByEos: "Paused by eos",
    pausedRemote: "Paused from the remote",
    waitingLook: "Waiting for a look",
    pause: "Pause",
    play: "Play",
  },
  viewers: {
    title: "Viewers",
    inZone: (viewers: number, looking: number) => `${viewers} in the zone · ${looking} looking`,
    nobody: "Nobody in the zone",
    ignored: "Ignored",
    ignoredWhy: "face-like print, never had landmarks",
    turnedAway: "turned away, no landmarks",
    angles: (yaw: string, pitch: string) => `yaw ${yaw}° · pitch ${pitch}°`,
    eyesDown: "eyes ↓",
    eyesDownTitle: "Eyes looking down",
    looking: "Looking",
    away: "Away",
  },
  settings: {
    title: "Settings",
    waiting: "Waiting for eos…",
    saved: "Saved",
    notSaved: "Not saved",
    severalViewers: "Several viewers",
    modes: { any_away: "Any away", all_away: "All away", nearest: "Nearest" },
    modeHints: {
      any_away: "Pause as soon as anyone in the zone looks away.",
      all_away: "Keep playing while at least one viewer watches.",
      nearest: "Follow only the viewer closest to the TV.",
    },
    pauseAfter: "Pause after looking away",
    resumeAfter: "Resume after looking back",
    whenNobody: "When nobody is there",
    faceLost: { pause: "Pause", ignore: "Keep playing" },
    after: "…after",
    headPose: "Head pose",
    screenDirection: "Screen direction",
    calibrateHint: ["Set by ", "Calibrate", " while looking at the screen."] as [string, string, string],
    yawTolerance: "Turn left/right allowed",
    pitchTolerance: "Tilt up/down allowed",
  },
  events: {
    title: "Events",
    empty: "No events yet",
    phrases: {
      started: (p: Params) => (p.dry_run ? "started (dry run: commands are only logged)" : "started"),
      stopped: () => "stopped",
      paused: (p: Params) => `paused: ${why(p)}`,
      resumed: (p: Params) => `resumed: ${why(p)}`,
      would_pause: (p: Params) => `would pause: ${why(p)}`,
      would_resume: (p: Params) => `would resume: ${why(p)}`,
      command_failed: (p: Params) => `${p.command} failed: ${p.error}`,
      not_confirmed: (p: Params) => `${p.command} was not confirmed by the Apple TV; may retry`,
      player: (p: Params) => {
        const details = [p.app, p.title].filter(Boolean).join(" - ");
        const playback = PLAYBACK[p.playback as Playback] ?? p.playback;
        return `player: ${playback}${details ? ` (${details})` : ""}`;
      },
      player_lost: () => "player: disconnected",
      paused_elsewhere: () => "paused by someone else: will not resume it",
      started_elsewhere: () => "playback started by someone else: waiting for a viewer to look",
      automation: (p: Params) => (p.enabled ? "automation on" : "automation off"),
      pressed: (p: Params) => `${p.action} pressed`,
      calibrated: (p: Params) =>
        `calibrated: screen at yaw ${signed(Number(p.yaw), 1)}, pitch ${signed(Number(p.pitch), 1)} (from ${p.poses} poses)`,
      calibration_failed: (p: Params) => `calibration failed: ${p.error}`,
      recording_started: (p: Params) => `recording to ${p.file}`,
      recording_saved: (p: Params) => `recording saved: ${p.file}`,
      step_recorded: (p: Params) =>
        `recorded step ${p.step}: ${p.frames} frames, face measured in ${Math.round(Number(p.face_share) * 100)}%`,
    } as Record<string, (params: Params) => string>,
  },
  offline: "Connection to eos lost. Reconnecting…",
  record: {
    title: "Gaze recording",
    intro:
      "Records how your head and eyes look while you do each step, so the pause thresholds can be tuned from real data. Only numbers are saved, no images.",
    stepOf: (step: number, total: number) => `Step ${step} of ${total}`,
    getReady: "Get ready",
    recording: "Recording",
    stats: (frames: number, share: string) => `${frames} frames · face measured in ${share}`,
    stopStep: "Stop this step",
    start: "Start",
    redoStep: (step: number) => `Redo step ${step}`,
    finish: "Finish",
    hint: "After Start you have 5 s to get into position. A beep marks the start, a double beep the end, so your eyes can stay where the step says.",
    allDone: "All steps recorded",
    allDoneHint: "Finish to close the file. Redo any step from the list if it went wrong.",
    savedTo: "Saved to",
    steps: "Steps",
    progress: (done: number, total: number, minutes: number) =>
      `${done} of ${total} done · about ${minutes} min`,
    face: (share: string) => `face ${share}`,
    take: (take: number) => `take ${take}`,
    redo: "Redo",
    redoTitle: "Record this step again",
    noFace: "No face",
    nobodyInZone: "nobody in the zone",
    faceChip: "Face",
    sound: "Sound",
    soundTitle: "Beeps when a step starts and ends",
    error: "Recording",
    labels: { screen: "screen", phone: "phone", elsewhere: "elsewhere", closed: "eyes closed" } as Record<
      string,
      string
    >,
    /** By step id; empty here: the server's English texts are shown as they are. */
    stepTexts: {} as Record<string, { title: string; instruction: string }>,
  },
};

export type Dict = typeof en;
