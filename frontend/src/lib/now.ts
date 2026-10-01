import type { Attention, StatusMessage } from "../protocol/types";
import { clamp01, seconds } from "./format";

export interface NowInfo {
  attention: Attention;
  detail: string;
  /** 0..1 towards the next automatic pause or resume; 0 when none is coming. */
  progress: number;
}

/** What the "now" badge says: the room's attention and what eos is about to do. */
export function describeNow(status: StatusMessage): NowInfo {
  const { room, machine, automation, player } = status;
  const behavior = status.settings.behavior;
  const { attention } = room;
  const streak = machine.streak_s;
  const playing = player.playback === "playing";
  const paused = player.playback === "paused";
  const towards = (limit: number, what: string): NowInfo => ({
    attention,
    detail: `${what} in ${seconds(limit - streak)}`,
    progress: clamp01(streak / limit),
  });
  const say = (detail: string): NowInfo => ({ attention, detail, progress: 0 });
  // A dry run only logs its commands: never promise a pause that will not happen.
  const pausing = automation.dry_run ? "would pause" : "pausing";
  const resuming = automation.dry_run ? "would resume" : "resuming";

  if (!automation.enabled) return say("automation is off");
  if (!player.connected) return say("Apple TV not connected");
  if (machine.pending) return say(machine.pending === "pause" ? "pausing…" : "resuming…");
  if (machine.skipped) return say(`dry run · would ${machine.skipped}, nothing sent`);
  if (playing && machine.armed && attention === "away") {
    return towards(behavior.pause_after_s, pausing);
  }
  if (playing && machine.armed && attention === "absent" && behavior.on_face_lost === "pause") {
    return towards(behavior.face_lost_after_s, `nobody here · ${pausing}`);
  }
  if (paused && machine.paused_by_us && attention === "looking") {
    return towards(behavior.resume_after_s, resuming);
  }
  if (paused && machine.paused_by_us) return say("paused by eos · look at the screen to resume");
  if (paused) return say("paused from the remote · left alone");
  if (playing && !machine.armed) return say("waiting for someone to look");
  if (playing) return say(attention === "looking" ? "watching" : "");
  return say(player.playback ? `player ${player.playback}` : "");
}
