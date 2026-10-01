"""Labelled recordings of the viewer's head pose and eyes, for tuning thresholds offline.

Two ways to label what the viewer was doing: `eos pose --record` takes it from the
keyboard, and the web UI's guided recording walks through scripted steps ("watch the
TV", "read your phone", ...), one Start press per step, and labels every row with it.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from eyes_on_screen.attention.classifier import Attention
from eyes_on_screen.vision.analyzer import FaceObservation

COUNTDOWN_S = 5.0
"""After Start: time to put the phone or laptop down and get into position."""

COLUMNS = (
    "t",
    "step",
    "take",
    "step_t",
    "label",
    "faces",
    "unconfirmed",
    "score",
    "face_w",
    "yaw",
    "pitch",
    "roll",
    "eye_down",
    "eye_up",
    "eye_closed",
    "eye_squint",
    "attention",
)


@dataclass(frozen=True, slots=True)
class Step:
    id: str
    """Stable name of the step, e.g. for the web UI to show it in another language."""
    label: str
    """What the viewer does: the class a threshold has to tell apart (screen, phone...)."""
    title: str
    instruction: str
    duration_s: float


GAZE_STEPS: tuple[Step, ...] = (
    Step(
        "watch_tv",
        "screen",
        "Watch the TV",
        "Sit as usual and watch the TV. Blink and move naturally.",
        40,
    ),
    Step(
        "phone_in_hands",
        "phone",
        "Phone in your hands",
        "Hold the phone at chest height and scroll through it, the way you usually do on the sofa.",
        40,
    ),
    Step(
        "phone_on_lap",
        "phone",
        "Phone on your lap",
        "Rest the phone on your lap and read from it.",
        40,
    ),
    Step("back_to_tv", "screen", "Back to the TV", "Look at the TV again.", 30),
    Step(
        "look_around",
        "elsewhere",
        "Look around",
        "Look anywhere but the TV: out of the window, to the sides, at someone next to you.",
        30,
    ),
    Step(
        "eyes_closed",
        "closed",
        "Close your eyes",
        "Lean back and close your eyes, as if dozing off.",
        20,
    ),
    Step("phone_again", "phone", "Phone again", "Back to the phone, held the way you like.", 30),
    Step("tv_once_more", "screen", "TV once more", "Finish by watching the TV.", 30),
)


class PoseRecorder:
    """Writes one CSV row per analysed frame: the target's pose and eyes, plus labels."""

    def __init__(self, path: Path, started: float) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._started = started
        # Line-buffered: a killed or crashed session still leaves its rows on disk.
        self._file = path.open("w", newline="", encoding="utf-8", buffering=1)
        self._writer = csv.writer(self._file)
        self._writer.writerow(COLUMNS)

    def write(
        self,
        now: float,
        faces: Sequence[FaceObservation],
        target: FaceObservation | None,
        attention: Attention,
        label: str,
        *,
        step: int | None = None,
        take: int | None = None,
        step_t: float | None = None,
    ) -> None:
        pose = target.pose if target else None
        eyes = target.eyes if target else None
        self._writer.writerow(
            [
                f"{now - self._started:.2f}",
                "" if step is None else step,
                "" if take is None else take,
                "" if step_t is None else f"{step_t:.2f}",
                label,
                len(faces),
                sum(face.pose is None for face in faces),
                f"{target.score:.2f}" if target else "",
                f"{target.box[2] - target.box[0]:.4f}" if target else "",
                f"{pose.yaw:.1f}" if pose else "",
                f"{pose.pitch:.1f}" if pose else "",
                f"{pose.roll:.1f}" if pose else "",
                f"{eyes.look_down:.3f}" if eyes else "",
                f"{eyes.look_up:.3f}" if eyes else "",
                f"{eyes.closed:.3f}" if eyes else "",
                f"{eyes.squint:.3f}" if eyes else "",
                attention.value,
            ]
        )

    def close(self) -> None:
        self._file.close()


class RecordingError(Exception):
    """A step cannot start now. User-facing message."""


class NoSuchStep(RecordingError):
    pass


@dataclass(frozen=True, slots=True)
class StepProgress:
    index: int
    phase: Literal["countdown", "recording"]
    remaining_s: float
    phase_s: float
    frames: int
    with_face: int


@dataclass(frozen=True, slots=True)
class StepResult:
    """The latest take of a finished step."""

    index: int
    take: int
    frames: int
    with_face: int
    """Frames where the viewer's face had landmarks, so pose and eyes were measured."""


@dataclass(slots=True)
class _Take:
    index: int
    number: int
    started: float
    frames: int = 0
    with_face: int = 0


class GuidedRecording:
    """Scripted steps recorded one at a time: Start, a countdown, then `duration_s` of rows.

    Rows carry the step's number, label and take, so a redone step simply has a newer
    take. The file is created by the first step. Time comes in as an argument, like in
    the state machine.
    """

    def __init__(self, path: Path, steps: Sequence[Step] = GAZE_STEPS) -> None:
        self.path = path
        self.steps = tuple(steps)
        self._recorder: PoseRecorder | None = None
        self._current: _Take | None = None
        self._takes: dict[int, int] = {}
        self._results: dict[int, StepResult] = {}
        self._last: int | None = None

    @property
    def results(self) -> list[StepResult]:
        return [self._results[index] for index in sorted(self._results)]

    @property
    def last(self) -> int | None:
        """The step finished most recently: the one a "Redo" button repeats."""
        return self._last

    def start(self, index: int, now: float) -> None:
        """Start step `index` (again, if it was done already); OSError if no file."""
        if not 0 <= index < len(self.steps):
            raise NoSuchStep(f"there is no step {index + 1}: the recording has {len(self.steps)}")
        self.update(now)
        if self._current is not None:
            raise RecordingError(f"step {self._current.index + 1} is still running")
        if self._recorder is None:
            self._recorder = PoseRecorder(self.path, now)
        number = self._takes.get(index, 0) + 1
        self._takes[index] = number
        self._current = _Take(index, number, now)

    def cancel(self) -> None:
        """Stop the running step; its rows stay in the file under their take number."""
        self._current = None

    def add(
        self,
        now: float,
        faces: Sequence[FaceObservation],
        target: FaceObservation | None,
        attention: Attention,
    ) -> None:
        """Record one analysed frame, if a step is past its countdown."""
        take = self._current
        if take is None or self._recorder is None:
            return
        step = self.steps[take.index]
        step_t = now - take.started - COUNTDOWN_S
        if not 0 <= step_t < step.duration_s:
            return
        take.frames += 1
        if target is not None and target.pose is not None:
            take.with_face += 1
        self._recorder.write(
            now,
            faces,
            target,
            attention,
            step.label,
            step=take.index + 1,
            take=take.number,
            step_t=step_t,
        )

    def update(self, now: float) -> StepResult | None:
        """End the running step once its time is up; returns its result then."""
        take = self._current
        if take is None or now < take.started + COUNTDOWN_S + self.steps[take.index].duration_s:
            return None
        self._current = None
        result = StepResult(take.index, take.number, take.frames, take.with_face)
        self._results[take.index] = result
        self._last = take.index
        return result

    def progress(self, now: float) -> StepProgress | None:
        take = self._current
        if take is None:
            return None
        step = self.steps[take.index]
        counting = now < take.started + COUNTDOWN_S
        end = take.started + COUNTDOWN_S + (0 if counting else step.duration_s)
        return StepProgress(
            index=take.index,
            phase="countdown" if counting else "recording",
            remaining_s=round(max(0.0, end - now), 2),
            phase_s=COUNTDOWN_S if counting else step.duration_s,
            frames=take.frames,
            with_face=take.with_face,
        )

    def close(self) -> None:
        self._current = None
        if self._recorder is not None:
            self._recorder.close()
