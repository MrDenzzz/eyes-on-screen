import { type ReactNode, useEffect, useRef, useState } from "react";

import { api } from "../api";
import { run } from "../eos";
import { clamp01, signed } from "../lib/format";
import { faceShare, formatClock, nextStep } from "../lib/recording";
import { cues, unlockSound } from "../lib/sound";
import type { RecordingInfo, RecordingProgress, RecordingResult, RecordingStepInfo } from "../protocol/types";
import { toast, useEos } from "../store";

const RING_LENGTH = 327; // circumference of the r=52 ring
const SOUND_KEY = "eos.recording.sound";

function useSound(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(() => {
    try {
      return localStorage.getItem(SOUND_KEY) !== "off";
    } catch {
      return true;
    }
  });
  function change(value: boolean) {
    if (value) unlockSound();
    setOn(value);
    try {
      localStorage.setItem(SOUND_KEY, value ? "on" : "off");
    } catch {
      // storage blocked: the choice lasts until the page reloads
    }
  }
  return [on, change];
}

/** Beeps on the countdown's last seconds, when recording starts and when the step ends. */
function useCues(current: RecordingProgress | null, enabled: boolean) {
  const previous = useRef<RecordingProgress | null>(null);
  useEffect(() => {
    const before = previous.current;
    previous.current = current;
    if (!enabled) return;
    if (current?.phase === "countdown") {
      const second = Math.ceil(current.remaining_s);
      const shown = before?.phase === "countdown" ? Math.ceil(before.remaining_s) : null;
      if (second <= 3 && second > 0 && second !== shown) cues.tick();
    } else if (current?.phase === "recording" && before?.phase === "countdown") {
      cues.start();
    } else if (!current && before?.phase === "recording") {
      cues.end();
    }
  }, [current, enabled]);
}

export function RecordPage() {
  const recording = useEos((state) => state.status?.recording ?? null);
  const [steps, setSteps] = useState<RecordingStepInfo[] | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [sound, setSound] = useSound();
  useCues(recording?.current ?? null, sound);

  useEffect(() => {
    api.recordingSteps().then(setSteps, (error: Error) => toast(`Recording steps: ${error.message}`, true));
  }, []);

  if (!steps) {
    return (
      <main className="record">
        <div className="card record-stage record-loading">
          <div className="spinner" />
        </div>
      </main>
    );
  }

  const done = new Map((recording?.done ?? []).map((result) => [result.index, result]));
  const current = recording?.current ?? null;
  const next = nextStep(steps.length, done);

  async function start(index: number) {
    if (sound) unlockSound();
    setSaved(null);
    await run(api.startRecordingStep(index), "Recording");
  }

  async function finish() {
    const file = recording?.file ?? null;
    if (await run(api.finishRecording(), "Recording")) setSaved(file);
  }

  return (
    <main className="record">
      <section className="card record-stage">
        <div className="card-head">
          <h2>Gaze recording</h2>
          {recording && <span className="muted record-file">{recording.file}</span>}
        </div>

        {current ? (
          <Running
            step={steps[current.index]!}
            progress={current}
            total={steps.length}
            onStop={() => void run(api.cancelRecordingStep(), "Recording")}
          />
        ) : next !== null ? (
          <Upcoming
            step={steps[next]!}
            index={next}
            total={steps.length}
            intro={!recording}
            recording={recording}
            onStart={(index) => void start(index)}
            onFinish={() => void finish()}
          />
        ) : (
          <AllDone recording={recording} onStart={(index) => void start(index)} onFinish={() => void finish()} />
        )}

        {saved && !recording && (
          <div className="record-saved">
            Saved to <code>{saved}</code>
          </div>
        )}

        <div className="record-foot">
          <LiveFace />
          <label className="switch" title="Beeps when a step starts and ends">
            <input type="checkbox" checked={sound} onChange={(event) => setSound(event.target.checked)} />
            <span className="track">
              <span className="thumb" />
            </span>
            <span>Sound</span>
          </label>
        </div>
      </section>

      <StepList
        steps={steps}
        done={done}
        current={current?.index ?? null}
        next={next}
        onRedo={(index) => void start(index)}
      />
    </main>
  );
}

function Ring({ fraction, children }: { fraction: number; children: ReactNode }) {
  return (
    <div className="ring">
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle cx="60" cy="60" r="52" className="ring-track" />
        <circle
          cx="60"
          cy="60"
          r="52"
          className="ring-arc"
          style={{ strokeDashoffset: RING_LENGTH * (1 - clamp01(fraction)) }}
        />
      </svg>
      <span>{children}</span>
    </div>
  );
}

function Running(props: {
  step: RecordingStepInfo;
  progress: RecordingProgress;
  total: number;
  onStop: () => void;
}) {
  const { step, progress, total, onStop } = props;
  const counting = progress.phase === "countdown";
  return (
    <div className={`record-now ${counting ? "is-countdown" : "is-recording"}`}>
      <Ring fraction={1 - progress.remaining_s / progress.phase_s}>
        {counting ? Math.ceil(progress.remaining_s) : formatClock(progress.remaining_s)}
      </Ring>
      <div className="record-phase">
        {counting ? (
          "Get ready"
        ) : (
          <>
            <i className="rec-dot" /> Recording
          </>
        )}
      </div>
      <div className="record-kicker">
        Step {progress.index + 1} of {total}
      </div>
      <div className="record-title">{step.title}</div>
      <p className="record-instruction">{step.instruction}</p>
      <div className="record-stats">
        {counting ? " " : `${progress.frames} frames · face measured in ${faceShare(progress)}`}
      </div>
      <div className="record-actions">
        <button className="btn" onClick={onStop}>
          Stop this step
        </button>
      </div>
    </div>
  );
}

function Upcoming(props: {
  step: RecordingStepInfo;
  index: number;
  total: number;
  intro: boolean;
  recording: RecordingInfo | null;
  onStart: (index: number) => void;
  onFinish: () => void;
}) {
  const { step, index, total, intro, recording, onStart, onFinish } = props;
  const last = recording?.last ?? null;
  return (
    <div className="record-next">
      {intro && (
        <p className="record-intro">
          Records how your head and eyes look while you do each step, so the pause thresholds can be tuned from real
          data. Only numbers are saved, no images.
        </p>
      )}
      <div className="record-kicker">
        Step {index + 1} of {total} · {step.duration_s} s
      </div>
      <div className="record-title">{step.title}</div>
      <p className="record-instruction">{step.instruction}</p>
      <div className="record-actions">
        <button className="btn btn-primary btn-lg" onClick={() => onStart(index)}>
          Start
        </button>
        {last !== null && (
          <button className="btn btn-lg" onClick={() => onStart(last)}>
            Redo step {last + 1}
          </button>
        )}
        {recording && (
          <button className="btn btn-lg" onClick={onFinish}>
            Finish
          </button>
        )}
      </div>
      <p className="hint">
        After Start you have 5 s to get into position. A beep marks the start, a double beep the end, so your eyes can
        stay where the step says.
      </p>
    </div>
  );
}

function AllDone(props: { recording: RecordingInfo | null; onStart: (index: number) => void; onFinish: () => void }) {
  const last = props.recording?.last ?? null;
  return (
    <div className="record-next">
      <div className="record-done-mark">✓</div>
      <div className="record-title">All steps recorded</div>
      <p className="record-instruction">Finish to close the file. Redo any step from the list if it went wrong.</p>
      <div className="record-actions">
        <button className="btn btn-primary btn-lg" onClick={props.onFinish}>
          Finish
        </button>
        {last !== null && (
          <button className="btn btn-lg" onClick={() => props.onStart(last)}>
            Redo step {last + 1}
          </button>
        )}
      </div>
    </div>
  );
}

function StepList(props: {
  steps: RecordingStepInfo[];
  done: ReadonlyMap<number, RecordingResult>;
  current: number | null;
  next: number | null;
  onRedo: (index: number) => void;
}) {
  const { steps, done, current, next, onRedo } = props;
  const minutes = Math.ceil(steps.reduce((sum, step) => sum + step.duration_s + 5, 0) / 60);
  return (
    <aside className="card record-steps">
      <div className="card-head">
        <h2>Steps</h2>
        <span className="muted">
          {done.size} of {steps.length} done · about {minutes} min
        </span>
      </div>
      <ol className="steps">
        {steps.map((step, index) => {
          const result = done.get(index);
          const state =
            current === index ? "running" : result ? "done" : index === next && current === null ? "next" : "todo";
          return (
            <li key={index} className={`step step-${state}`}>
              <span className="step-num">{state === "done" ? "✓" : index + 1}</span>
              <div>
                <div className="step-title">{step.title}</div>
                <div className="step-meta">
                  <span className={`tag tag-${step.label}`}>{step.label}</span>
                  <span>{step.duration_s} s</span>
                  {result && <span>face {faceShare(result)}</span>}
                  {result && result.take > 1 && <span>take {result.take}</span>}
                </div>
              </div>
              {result && current === null ? (
                <button className="btn btn-sm" onClick={() => onRedo(index)} title="Record this step again">
                  Redo
                </button>
              ) : (
                <span />
              )}
            </li>
          );
        })}
      </ol>
    </aside>
  );
}

/** Whether the camera sees the viewer right now: the recording is only useful if it does. */
function LiveFace() {
  const face = useEos((state) => state.frame?.header.faces.find((f) => f.focus) ?? null);
  if (!face) {
    return (
      <div className="record-live">
        <span className="chip state-absent">No face</span>
        <span className="muted">nobody in the zone</span>
      </div>
    );
  }
  return (
    <div className="record-live">
      <span className={`chip state-${face.state === "looking" ? "looking" : "away"}`}>Face</span>
      <span className="viewer-angles">
        {face.yaw === null || face.pitch === null
          ? "no landmarks"
          : `yaw ${signed(face.yaw)}° · pitch ${signed(face.pitch)}°`}
      </span>
      {face.eyes_down !== null && (
        <span className="eyes" title="Eyes looking down">
          eyes ↓
          <span className="eyes-meter">
            <i style={{ width: `${Math.round(face.eyes_down * 100)}%` }} />
          </span>
        </span>
      )}
    </div>
  );
}
