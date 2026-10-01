import type { Dict } from "../i18n";
import type { Attention, StatusMessage } from "../protocol/types";
import { clamp01 } from "./format";

export interface NowInfo {
  attention: Attention;
  detail: string;
  /** 0..1 towards the next automatic pause or resume; 0 when none is coming. */
  progress: number;
}

/** What the "now" badge says: the room's attention and what eos is about to do. */
export function describeNow(status: StatusMessage, t: Dict): NowInfo {
  const { room, machine, automation, player } = status;
  const behavior = status.settings.behavior;
  const words = t.now;
  const { attention } = room;
  const streak = machine.streak_s;
  const playing = player.playback === "playing";
  const paused = player.playback === "paused";
  const towards = (limit: number, what: string): NowInfo => ({
    attention,
    detail: words.countdown(what, t.fmt.seconds(limit - streak)),
    progress: clamp01(streak / limit),
  });
  const say = (detail: string): NowInfo => ({ attention, detail, progress: 0 });
  // A dry run only logs its commands: never promise a pause that will not happen.
  const pausing = automation.dry_run ? words.wouldPause : words.pausing;
  const resuming = automation.dry_run ? words.wouldResume : words.resuming;

  if (!automation.enabled) return say(words.automationOff);
  if (!player.connected) return say(words.notConnected);
  if (machine.pending) return say(machine.pending === "pause" ? words.pausingNow : words.resumingNow);
  if (machine.skipped) return say(words.skipped(machine.skipped));
  if (playing && machine.armed && attention === "away") {
    return towards(behavior.pause_after_s, pausing);
  }
  if (playing && machine.armed && attention === "absent" && behavior.on_face_lost === "pause") {
    return towards(behavior.face_lost_after_s, words.nobodyHere(pausing));
  }
  if (paused && machine.paused_by_us && attention === "looking") {
    return towards(behavior.resume_after_s, resuming);
  }
  if (paused && machine.paused_by_us) return say(words.pausedByEos);
  if (paused) return say(words.pausedRemote);
  if (playing && !machine.armed) return say(words.waitingLook);
  if (playing) return say(attention === "looking" ? words.watching : "");
  return say(player.playback ? words.player(t.playback[player.playback]) : "");
}
