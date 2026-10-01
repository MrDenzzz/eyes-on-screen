import { type CSSProperties, useEffect, useRef, useState } from "react";

import { api } from "../api";
import { run } from "../eos";
import { useT } from "../hooks/useT";
import type { SettingsChanges } from "../protocol/types";
import { useEos } from "../store";

const SAVE_DELAY_MS = 350;
const SAVED_FLASH_MS = 1500;

function useSavedFlash(): [boolean, () => void] {
  const [shown, setShown] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  return [
    shown,
    () => {
      setShown(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setShown(false), SAVED_FLASH_MS);
    },
  ];
}

interface SegmentedProps<T extends string> {
  label: string;
  value: T;
  options: Record<T, string>;
  onChange(value: T): void;
}

export function Segmented<T extends string>({ label, value, options, onChange }: SegmentedProps<T>) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {(Object.keys(options) as T[]).map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={option === value}
          className={option === value ? "on" : ""}
          onClick={() => option !== value && onChange(option)}
        >
          {options[option]}
        </button>
      ))}
    </div>
  );
}

interface RangeProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format(value: number): string;
  onCommit(value: number): Promise<boolean>;
}

/** A slider that follows the server's value, except while the user is moving it. */
export function RangeSetting({ label, value, min, max, step, format, onCommit }: RangeProps) {
  const [local, setLocal] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const shown = local ?? value;

  function change(next: number) {
    setLocal(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      void onCommit(next).then(() => setLocal(null));
    }, SAVE_DELAY_MS);
  }

  const fill = { "--fill": `${((shown - min) / (max - min)) * 100}%` } as CSSProperties;
  return (
    <div className="setting">
      <div className="setting-label">
        {label} <output>{format(shown)}</output>
      </div>
      <input
        type="range"
        aria-label={label}
        min={min}
        max={max}
        step={step}
        value={shown}
        style={fill}
        onChange={(event) => change(Number(event.target.value))}
      />
    </div>
  );
}

export function SettingsCard() {
  const settings = useEos((state) => state.status?.settings ?? null);
  const t = useT();
  const words = t.settings;
  const [saved, flashSaved] = useSavedFlash();

  async function save(changes: SettingsChanges): Promise<boolean> {
    const ok = await run(api.changeSettings(changes), words.notSaved);
    if (ok) flashSaved();
    return ok;
  }

  if (!settings) {
    return (
      <div className="card">
        <div className="card-head">
          <h2>{words.title}</h2>
        </div>
        <div className="hint">{words.waiting}</div>
      </div>
    );
  }
  const { behavior, pose } = settings;
  const { seconds, degrees, signed } = t.fmt;
  const [hintBefore, hintButton, hintAfter] = words.calibrateHint;

  return (
    <div className="card">
      <div className="card-head">
        <h2>{words.title}</h2>
        <span className={`saved${saved ? " show" : ""}`}>{words.saved}</span>
      </div>

      <div className="setting">
        <div className="setting-label">{words.severalViewers}</div>
        <Segmented
          label={words.severalViewers}
          value={behavior.multiple_viewers}
          options={words.modes}
          onChange={(multiple_viewers) => void save({ behavior: { multiple_viewers } })}
        />
        <div className="hint">{words.modeHints[behavior.multiple_viewers]}</div>
      </div>

      <RangeSetting
        label={words.pauseAfter}
        value={behavior.pause_after_s}
        min={0.5}
        max={5}
        step={0.1}
        format={seconds}
        onCommit={(pause_after_s) => save({ behavior: { pause_after_s } })}
      />
      <RangeSetting
        label={words.resumeAfter}
        value={behavior.resume_after_s}
        min={0.1}
        max={3}
        step={0.1}
        format={seconds}
        onCommit={(resume_after_s) => save({ behavior: { resume_after_s } })}
      />

      <div className="setting">
        <div className="setting-label">{words.whenNobody}</div>
        <Segmented
          label={words.whenNobody}
          value={behavior.on_face_lost}
          options={words.faceLost}
          onChange={(on_face_lost) => void save({ behavior: { on_face_lost } })}
        />
      </div>
      {behavior.on_face_lost === "pause" && (
        <RangeSetting
          label={words.after}
          value={behavior.face_lost_after_s}
          min={1}
          max={15}
          step={0.5}
          format={seconds}
          onCommit={(face_lost_after_s) => save({ behavior: { face_lost_after_s } })}
        />
      )}

      <div className="setting-group">{words.headPose}</div>
      <div className="setting">
        <div className="setting-label">
          {words.screenDirection}
          <output>{t.viewers.angles(signed(pose.yaw_center_deg, 1), signed(pose.pitch_center_deg, 1))}</output>
        </div>
        <div className="hint">
          {hintBefore}
          <b>{hintButton}</b>
          {hintAfter}
        </div>
      </div>
      <RangeSetting
        label={words.yawTolerance}
        value={pose.yaw_tolerance_deg}
        min={5}
        max={45}
        step={1}
        format={degrees}
        onCommit={(yaw_tolerance_deg) => save({ pose: { yaw_tolerance_deg } })}
      />
      <RangeSetting
        label={words.pitchTolerance}
        value={pose.pitch_tolerance_deg}
        min={5}
        max={40}
        step={1}
        format={degrees}
        onCommit={(pitch_tolerance_deg) => save({ pose: { pitch_tolerance_deg } })}
      />
    </div>
  );
}
