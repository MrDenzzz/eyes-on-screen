/** Short beeps for the guided recording: the viewer watches the TV, not the page. */

let context: AudioContext | null = null;

/** Call from a click handler: browsers only allow audio after a user gesture. */
export function unlockSound(): void {
  if (typeof AudioContext === "undefined") return;
  context ??= new AudioContext();
  void context.resume();
}

function tone(audio: AudioContext, at: number, seconds: number, frequency: number): void {
  const oscillator = audio.createOscillator();
  const gain = audio.createGain();
  oscillator.frequency.value = frequency;
  // Ramps instead of a hard on/off, which clicks.
  gain.gain.setValueAtTime(0.0001, at);
  gain.gain.exponentialRampToValueAtTime(0.35, at + 0.012);
  gain.gain.exponentialRampToValueAtTime(0.0001, at + seconds);
  oscillator.connect(gain).connect(audio.destination);
  oscillator.start(at);
  oscillator.stop(at + seconds + 0.02);
}

function beeps(lengthsMs: readonly number[], frequency: number): void {
  if (!context) return;
  let at = context.currentTime;
  for (const ms of lengthsMs) {
    tone(context, at, ms / 1000, frequency);
    at += ms / 1000 + 0.09;
  }
}

export const cues = {
  /** Each of the last three seconds of the countdown. */
  tick: () => beeps([80], 660),
  /** Recording starts. */
  start: () => beeps([300], 990),
  /** The step is over. */
  end: () => beeps([150, 150], 740),
};
