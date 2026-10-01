import { type ReactNode, useEffect, useRef, useState } from "react";

import { api } from "../api";
import { run } from "../eos";
import { useT } from "../hooks/useT";
import type { Dict } from "../i18n";
import { clamp01 } from "../lib/format";
import { faceShare, formatClock, nextStep } from "../lib/recording";
import { cues, unlockSound } from "../lib/sound";
import type { RecordingInfo, RecordingProgress, RecordingResult, RecordingStepInfo } from "../protocol/types";
import { toast, useEos } from "../store";

const RING_LENGTH = 327; // circumference of the r=52 ring
const SOUND_KEY = "eos.recording.sound";

/** A step's title and instruction in the viewer's language; the server's English otherwise. */
function stepText(step: RecordingStepInfo, t: Dict): { title: string; instruction: string } {
  return t.record.stepTexts[step.id] ?? step;
}

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
  const t = useT();
  const words = t.record;
  const [steps, setSteps] = useState<RecordingStepInfo[] | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [sound, setSound] = useSound();
  useCues(recording?.current ?? null, sound);

  useEffect(() => {
    api.recordingSteps().then(setSteps, (error: Error) => toast(`${words.error}: ${error.message}`, true));
  }, [words.error]);

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
    await run(api.startRecordingStep(index), words.error);
  }

  async function finish() {
    const file = recording?.file ?? null;
    if (await run(api.finishRecording(), words.error)) setSaved(file);
  }

  return (
    <main className="record">
      <section className="card record-stage">
        <div className="card-head">
          <h2>{words.title}</h2>
          {recording && <span className="muted record-file">{recording.file}</span>}
        </div>

        {current ? (
          <Running
            step={steps[current.index]!}
            progress={current}
            total={steps.length}
            onStop={() => void run(api.cancelRecordingStep(), words.error)}
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
            {words.savedTo} <code>{saved}</code>
          </div>
        )}

        <div className="record-foot">
          <LiveFace />
          <label className="switch" title={words.soundTitle}>
            <input type="checkbox" checked={sound} onChange={(event) => setSound(event.target.checked)} />
            <span className="track">
              <span className="thumb" />
            </span>
            <span>{words.sound}</span>
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
  const t = useT();
  const words = t.record;
  const text = stepText(step, t);
  const counting = progress.phase === "countdown";
  return (
    <div className={`record-now ${counting ? "is-countdown" : "is-recording"}`}>
      <Ring fraction={1 - progress.remaining_s / progress.phase_s}>
        {counting ? Math.ceil(progress.remaining_s) : formatClock(progress.remaining_s)}
      </Ring>
      <div className="record-phase">
        {counting ? (
          words.getReady
        ) : (
          <>
            <i className="rec-dot" /> {words.recording}
          </>
        )}
      </div>
      <div className="record-kicker">{words.stepOf(progress.index + 1, total)}</div>
      <div className="record-title">{text.title}</div>
      <p className="record-instruction">{text.instruction}</p>
      <div className="record-stats">{counting ? " " : words.stats(progress.frames, faceShare(progress))}</div>
      <div className="record-actions">
        <button className="btn" onClick={onStop}>
          {words.stopStep}
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
  const t = useT();
  const words = t.record;
  const text = stepText(step, t);
  const last = recording?.last ?? null;
  return (
    <div className="record-next">
      {intro && <p className="record-intro">{words.intro}</p>}
      <div className="record-kicker">
        {words.stepOf(index + 1, total)} · {t.fmt.duration(step.duration_s)}
      </div>
      <div className="record-title">{text.title}</div>
      <p className="record-instruction">{text.instruction}</p>
      <div className="record-actions">
        <button className="btn btn-primary btn-lg" onClick={() => onStart(index)}>
          {words.start}
        </button>
        {last !== null && (
          <button className="btn btn-lg" onClick={() => onStart(last)}>
            {words.redoStep(last + 1)}
          </button>
        )}
        {recording && (
          <button className="btn btn-lg" onClick={onFinish}>
            {words.finish}
          </button>
        )}
      </div>
      <p className="hint">{words.hint}</p>
    </div>
  );
}

function AllDone(props: { recording: RecordingInfo | null; onStart: (index: number) => void; onFinish: () => void }) {
  const words = useT().record;
  const last = props.recording?.last ?? null;
  return (
    <div className="record-next">
      <div className="record-done-mark">✓</div>
      <div className="record-title">{words.allDone}</div>
      <p className="record-instruction">{words.allDoneHint}</p>
      <div className="record-actions">
        <button className="btn btn-primary btn-lg" onClick={props.onFinish}>
          {words.finish}
        </button>
        {last !== null && (
          <button className="btn btn-lg" onClick={() => props.onStart(last)}>
            {words.redoStep(last + 1)}
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
  const t = useT();
  const words = t.record;
  const minutes = Math.ceil(steps.reduce((sum, step) => sum + step.duration_s + 5, 0) / 60);
  return (
    <aside className="card record-steps">
      <div className="card-head">
        <h2>{words.steps}</h2>
        <span className="muted">{words.progress(done.size, steps.length, minutes)}</span>
      </div>
      <ol className="steps">
        {steps.map((step, index) => {
          const result = done.get(index);
          const state =
            current === index ? "running" : result ? "done" : index === next && current === null ? "next" : "todo";
          return (
            <li key={step.id} className={`step step-${state}`}>
              <span className="step-num">{state === "done" ? "✓" : index + 1}</span>
              <div>
                <div className="step-title">{stepText(step, t).title}</div>
                <div className="step-meta">
                  <span className={`tag tag-${step.label}`}>{words.labels[step.label] ?? step.label}</span>
                  <span>{t.fmt.duration(step.duration_s)}</span>
                  {result && <span>{words.face(faceShare(result))}</span>}
                  {result && result.take > 1 && <span>{words.take(result.take)}</span>}
                </div>
              </div>
              {result && current === null ? (
                <button className="btn btn-sm" onClick={() => onRedo(index)} title={words.redoTitle}>
                  {words.redo}
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
  const t = useT();
  const words = t.record;
  if (!face) {
    return (
      <div className="record-live">
        <span className="chip state-absent">{words.noFace}</span>
        <span className="muted">{words.nobodyInZone}</span>
      </div>
    );
  }
  return (
    <div className="record-live">
      <span className={`chip state-${face.state === "looking" ? "looking" : "away"}`}>{words.faceChip}</span>
      <span className="viewer-angles">
        {face.yaw === null || face.pitch === null
          ? t.video.noLandmarks
          : t.viewers.angles(t.fmt.signed(face.yaw), t.fmt.signed(face.pitch))}
      </span>
      {face.eyes_down !== null && (
        <span className="eyes" title={t.viewers.eyesDownTitle}>
          {t.viewers.eyesDown}
          <span className="eyes-meter">
            <i style={{ width: `${Math.round(face.eyes_down * 100)}%` }} />
          </span>
        </span>
      )}
    </div>
  );
}
