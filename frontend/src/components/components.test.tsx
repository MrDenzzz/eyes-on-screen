import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { initialState, useEos } from "../store";
import { makeStatus } from "../test/fixtures";
import { PlayerCard } from "./PlayerCard";
import { SettingsCard } from "./SettingsCard";

const send = vi.hoisted(() => vi.fn(async () => true));
vi.mock("../eos", () => ({ send }));

beforeEach(() => {
  useEos.setState(initialState, true);
  send.mockClear();
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

    expect(send).toHaveBeenCalledWith({ cmd: "set", changes: { behavior: { multiple_viewers: "all_away" } } }, "Not saved");
  });

  it("saves a slider once the user stops moving it", () => {
    vi.useFakeTimers();
    useEos.setState({ status: makeStatus() });
    render(<SettingsCard />);

    const slider = screen.getByRole("slider", { name: "Pause after looking away" });
    fireEvent.change(slider, { target: { value: "2" } });
    fireEvent.change(slider, { target: { value: "2.5" } });
    expect(send).not.toHaveBeenCalled();
    act(() => void vi.advanceTimersByTime(400));

    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith({ cmd: "set", changes: { behavior: { pause_after_s: 2.5 } } }, "Not saved");
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

    expect(send).toHaveBeenCalledWith({ cmd: "player", action: "pause" }, "Pause");
  });
});
