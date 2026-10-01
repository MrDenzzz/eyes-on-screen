import { describe, expect, it } from "vitest";

import { decodeFrame } from "../protocol/frame";
import { makeStatus } from "../test/fixtures";
import { seconds, signed } from "./format";
import { pageFromHash } from "../hooks/usePage";
import { eventText } from "../i18n";
import { en } from "../i18n/en";
import { ruPlural } from "../i18n/plural";
import { ru } from "../i18n/ru";
import { describeNow } from "./now";
import { faceShare, formatClock, nextStep } from "./recording";
import { MAX_GAP_MS, toRuns } from "./timeline";

describe("decodeFrame", () => {
  it("splits the length-prefixed JSON header from the JPEG", () => {
    const header = new TextEncoder().encode(JSON.stringify({ seq: 7, ts: 1, attention: "away", faces: [] }));
    const jpeg = [0xff, 0xd8, 0xff];
    const buffer = new ArrayBuffer(4 + header.length + jpeg.length);
    new DataView(buffer).setUint32(0, header.length);
    new Uint8Array(buffer).set(header, 4);
    new Uint8Array(buffer).set(jpeg, 4 + header.length);

    const frame = decodeFrame(buffer);

    expect(frame.header.seq).toBe(7);
    expect([...frame.jpeg]).toEqual(jpeg);
  });
});

describe("toRuns", () => {
  const at = (ts: number, attention: "looking" | "away" | "absent") => ({ ts, attention });

  it("merges equal neighbours into one run per attention change", () => {
    const runs = toRuns([at(0, "looking"), at(100, "looking"), at(200, "away"), at(300, "away")], 400);

    expect(runs).toEqual([
      { attention: "looking", start: 0, end: 200 },
      { attention: "away", start: 200, end: 400 },
    ]);
  });

  it("leaves a stalled stretch of video empty", () => {
    const runs = toRuns([at(0, "looking"), at(100 + MAX_GAP_MS + 1, "looking")], 2000 + MAX_GAP_MS);

    expect(runs).toHaveLength(2);
    expect(runs[0]!.end).toBeLessThan(runs[1]!.start);
  });

  it("has nothing to draw without points", () => {
    expect(toRuns([], 1000)).toEqual([]);
  });
});

describe("describeNow", () => {
  it("counts down to a pause while the viewers look away", () => {
    const now = describeNow(makeStatus({ room: { attention: "away" }, machine: { streak_s: 0.6 } }), en);

    expect(now.detail).toBe("pausing in 0.9 s");
    expect(now.progress).toBeCloseTo(0.4);
  });

  it("counts down to resuming its own pause", () => {
    const now = describeNow(
      makeStatus({
        player: { playback: "paused" },
        machine: { paused_by_us: true, streak_s: 0.25 },
        room: { attention: "looking" },
      }),
      en,
    );

    expect(now.detail).toBe("resuming in 0.3 s");
    expect(now.progress).toBeCloseTo(0.5);
  });

  it("never promises a pause in a dry run", () => {
    const counting = describeNow(
      makeStatus({ automation: { dry_run: true }, room: { attention: "away" }, machine: { streak_s: 0.6 } }),
      en,
    );
    const decided = describeNow(
      makeStatus({ automation: { dry_run: true }, room: { attention: "away" }, machine: { skipped: "pause" } }),
      en,
    );

    expect(counting.detail).toBe("would pause in 0.9 s");
    expect(decided.detail).toBe("dry run · would pause, nothing sent");
    expect(decided.progress).toBe(0);
  });

  it("leaves a pause from the remote alone", () => {
    const now = describeNow(makeStatus({ player: { playback: "paused" }, machine: { paused_by_us: false } }), en);

    expect(now.detail).toBe("paused from the remote · left alone");
    expect(now.progress).toBe(0);
  });

  it("does nothing while automation is off", () => {
    const now = describeNow(makeStatus({ automation: { enabled: false }, room: { attention: "away" } }), en);

    expect(now.detail).toBe("automation is off");
  });

  it("waits for a look after a manual play", () => {
    const now = describeNow(makeStatus({ machine: { armed: false }, room: { attention: "away" } }), en);

    expect(now.detail).toBe("waiting for someone to look");
  });
});

describe("format", () => {
  it("uses a real minus sign and never negative seconds", () => {
    expect(signed(-12)).toBe("−12");
    expect(signed(3.14, 1)).toBe("+3.1");
    expect(seconds(-0.2)).toBe("0.0 s");
  });
});

describe("recording helpers", () => {
  it("picks the first step without a take", () => {
    expect(nextStep(3, new Map([[0, {}], [2, {}]]))).toBe(1);
    expect(nextStep(2, new Map([[0, {}], [1, {}]]))).toBeNull();
  });

  it("formats the share of frames with a face and the time left", () => {
    expect(faceShare({ frames: 400, with_face: 384 })).toBe("96%");
    expect(faceShare({ frames: 0, with_face: 0 })).toBe("–");
    expect(formatClock(12.3)).toBe("0:13");
    expect(formatClock(75)).toBe("1:15");
    expect(formatClock(-1)).toBe("0:00");
  });

  it("routes #record to the recording page", () => {
    expect(pageFromHash("#record")).toBe("record");
    expect(pageFromHash("")).toBe("live");
  });
});

describe("Russian", () => {
  it("counts down with a decimal comma", () => {
    const now = describeNow(makeStatus({ room: { attention: "away" }, machine: { streak_s: 0.6 } }), ru);

    expect(now.detail).toBe("пауза через 0,9 с");
  });

  it("picks the plural form", () => {
    expect([1, 3, 5, 21].map((n) => ruPlural(n, ["кадр", "кадра", "кадров"]))).toEqual([
      "кадр",
      "кадра",
      "кадров",
      "кадр",
    ]);
  });

  it("phrases events from their code and values, and falls back to the server text", () => {
    const event = { ts: 1, time: "12:00:00", level: "info", kind: "pause", text: "paused: looked away for 1.6s" } as const;
    const paused = { ...event, code: "paused", params: { reason: "looked_away", seconds: 1.6 } };
    const unknown = { ...event, code: "something_new", params: {} };

    expect(eventText(paused, ru)).toBe("пауза: отвлёкся на 1,6 с");
    expect(eventText(paused, en)).toBe("paused: looked away for 1.6s");
    expect(eventText(unknown, ru)).toBe("paused: looked away for 1.6s");
  });
});
