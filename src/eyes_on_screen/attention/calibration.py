"""Calibrating which head pose means "looking at the screen"."""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from eyes_on_screen.config import PoseConfig
from eyes_on_screen.vision.head_pose import HeadPose

MIN_SAMPLES = 5


class CalibrationError(Exception):
    """Not enough or unusable samples. User-facing message."""


class CalibrationSession:
    """Collects the viewer's head poses for a while, after a countdown to get ready."""

    def __init__(self, now: float, delay_s: float, duration_s: float) -> None:
        self.delay_s = delay_s
        self.duration_s = duration_s
        self.start = now + delay_s
        self.end = self.start + duration_s
        self.poses: list[HeadPose] = []

    def add(self, now: float, pose: HeadPose | None) -> None:
        if pose is not None and self.start <= now <= self.end:
            self.poses.append(pose)

    def finished(self, now: float) -> bool:
        return now > self.end

    def counting_down(self, now: float) -> bool:
        return now < self.start

    def remaining_s(self, now: float) -> float:
        """Seconds left in the current phase (countdown, then collecting)."""
        return max(0.0, (self.start if self.counting_down(now) else self.end) - now)


def calibrate_center(poses: Sequence[HeadPose], current: PoseConfig) -> PoseConfig:
    """Use the median pose of a viewer looking at the screen as the new centre.

    The camera sits below the TV, so looking at the screen is never 0/0: the face
    points somewhat above the camera. The median ignores the odd bad frame.
    """
    if len(poses) < MIN_SAMPLES:
        raise CalibrationError(
            f"need at least {MIN_SAMPLES} poses of the viewer, got {len(poses)}: "
            "look at the screen and hold still for a second"
        )
    update = {
        "yaw_center_deg": round(statistics.median(p.yaw for p in poses), 1),
        "pitch_center_deg": round(statistics.median(p.pitch for p in poses), 1),
    }
    try:
        return PoseConfig.model_validate(current.model_dump() | update)
    except ValueError as exc:
        raise CalibrationError(f"implausible centre {update}: {exc}") from exc
