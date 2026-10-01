"""Turning one observation into looking / away / absent."""

from __future__ import annotations

from enum import StrEnum

from eyes_on_screen.config import PoseConfig
from eyes_on_screen.vision.analyzer import FaceObservation


class Attention(StrEnum):
    LOOKING = "looking"
    AWAY = "away"
    ABSENT = "absent"


def classify(face: FaceObservation | None, pose: PoseConfig) -> Attention:
    if face is None:
        return Attention.ABSENT
    if face.pose is None:
        # A face is there but has no landmarks: in practice it is turned too far
        # (profile, looking down at a phone) or covered.
        return Attention.AWAY
    yaw_off = face.pose.yaw - pose.yaw_center_deg
    pitch_off = face.pose.pitch - pose.pitch_center_deg
    if abs(yaw_off) <= pose.yaw_tolerance_deg and abs(pitch_off) <= pose.pitch_tolerance_deg:
        return Attention.LOOKING
    return Attention.AWAY
