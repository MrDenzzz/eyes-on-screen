import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { initialState, useEos } from "../store";
import { makeStatus } from "../test/fixtures";
import { PlayerCard } from "./PlayerCard";
import { RecordPage } from "./RecordPage";
import { SettingsCard } from "./SettingsCard";

const STEPS = [
  { label: "screen", title: "Watch the TV", instruction: "Watch it.", duration_s: 40 },
  { label: "phone", title: "Phone in your hands", instruction: "Scroll it.", duration_s: 30 },
];

const api = vi.hoisted(() => ({
  changeSettings: vi.fn(async () => undefined),
  calibrate: vi.fn(async () => undefined),
  setAutomation: vi.fn(async () => undefined),
  press: vi.fn(async () => undefined),
  recordingSteps: vi.fn(async () => STEPS),
  startRecordingStep: vi.fn(async () => undefined),
  cancelRecordingStep: vi.fn(async () => undefined),
  finishRecording: vi.fn(async () => undefined),
}));
vi.mock("../api", () => ({ api }));

beforeEach(() => {
  useEos.setState(initialState, true);
  for (const call of Object.values(api)) call.mockClear();
});
afterEach(cleanup);

describe("SettingsCard", () => {
  it("shows the current settings", () => {
    useEos.setState({ status: makeStatus() });
    render(<SettingsCard />);

    expect(screen.getByRole("radio", { name: "Any away" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("Pause as soon as anyone in the zone looks away.")).toBeTruthy();
    expect(screen.getByText("yaw +2.9° · pitch +3.6°")).toBeTruthy();
  });

  it("sends the chosen several-viewers mode", () => {
    useEos.setState({ status: makeStatus() });
    render(<SettingsCard />);

    fireEvent.click(screen.getByRole("radio", { name: "All away" }));

    expect(api.changeSettings).toHaveBeenCalledWith({ behavior: { multiple_viewers: "all_away" } });
  });

  it("saves a slider once the user stops moving it", () => {
    vi.useFakeTimers();
    useEos.setState({ status: makeStatus() });
    render(<SettingsCard />);

    const slider = screen.getByRole("slider", { name: "Pause after looking away" });
    fireEvent.change(slider, { target: { value: "2" } });
    fireEvent.change(slider, { target: { value: "2.5" } });
    expect(api.changeSettings).not.toHaveBeenCalled();
    act(() => void vi.advanceTimersByTime(400));

    expect(api.changeSettings).toHaveBeenCalledTimes(1);
    expect(api.changeSettings).toHaveBeenCalledWith({ behavior: { pause_after_s: 2.5 } });
    vi.useRealTimers();
  });

  it("hides the delay when nobody-there means keep playing", () => {
    useEos.setState({ status: makeStatus({ settings: { behavior: { ...makeStatus().settings.behavior, on_face_lost: "ignore" } } }) });
    render(<SettingsCard />);

    expect(screen.queryByRole("slider", { name: "…after" })).toBeNull();
  });
});

describe("PlayerCard", () => {
  it("marks a pause made by eos and offers Play", () => {
    useEos.setState({ status: makeStatus({ player: { playback: "paused" }, machine: { paused_by_us: true } }) });
    render(<PlayerCard />);

    expect(screen.getByText("Paused by eos")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Play" }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "Pause" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("tells a pause from the remote apart", () => {
    useEos.setState({ status: makeStatus({ player: { playback: "paused" }, machine: { paused_by_us: false } }) });
    render(<PlayerCard />);

    expect(screen.getByText("Paused from the remote")).toBeTruthy();
  });

  it("sends pause", () => {
    useEos.setState({ status: makeStatus() });
    render(<PlayerCard />);

    fireEvent.click(screen.getByRole("button", { name: "Pause" }));

    expect(api.press).toHaveBeenCalledWith("pause");
  });
});

describe("RecordPage", () => {
  const recording = (overrides: object) => ({ file: "logs/recordings/gaze.csv", current: null, done: [], last: null, ...overrides });

  it("offers the first step and starts it", async () => {
    useEos.setState({ status: makeStatus() });
    render(<RecordPage />);

    expect(await screen.findByText("Watch the TV", { selector: ".record-title" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start" }));

    expect(api.startRecordingStep).toHaveBeenCalledWith(0);
  });

  it("moves on to the next step and can redo the last one", async () => {
    const done = [{ index: 0, take: 1, frames: 400, with_face: 384 }];
    useEos.setState({ status: makeStatus({ recording: recording({ done, last: 0 }) }) });
    render(<RecordPage />);

    expect(await screen.findByText("Phone in your hands", { selector: ".record-title" })).toBeTruthy();
    expect(screen.getByText("face 96%")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Redo step 1" }));

    expect(api.startRecordingStep).toHaveBeenCalledWith(0);
  });

  it("shows the running step with its timer and can stop it", async () => {
    const current = { index: 1, phase: "recording", remaining_s: 12.3, phase_s: 30, frames: 170, with_face: 85 };
    useEos.setState({ status: makeStatus({ recording: recording({ current }) }) });
    render(<RecordPage />);

    expect(await screen.findByText("0:13")).toBeTruthy();
    expect(screen.getByText("170 frames · face measured in 50%")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stop this step" }));

    expect(api.cancelRecordingStep).toHaveBeenCalled();
  });

  it("finishes once every step is done", async () => {
    const done = [
      { index: 0, take: 1, frames: 400, with_face: 400 },
      { index: 1, take: 2, frames: 300, with_face: 290 },
    ];
    useEos.setState({ status: makeStatus({ recording: recording({ done, last: 1 }) }) });
    render(<RecordPage />);

    expect(await screen.findByText("All steps recorded")).toBeTruthy();
    expect(screen.getByText("take 2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Finish" }));

    expect(api.finishRecording).toHaveBeenCalled();
  });
});
