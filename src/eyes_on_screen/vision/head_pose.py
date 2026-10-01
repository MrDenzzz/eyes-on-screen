"""Head orientation from MediaPipe's facial transformation matrix."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class HeadPose:
    """Where the face points, in degrees, relative to the line from the face to the camera.

    0/0 means the face looks straight into the camera.
    """

    yaw: float
    """Positive: the face turns towards the right edge of the image."""
    pitch: float
    """Positive: the face turns up."""
    roll: float
    """Positive: the top of the head tilts towards the right edge of the image."""


def head_pose_from_matrix(matrix: np.ndarray) -> HeadPose:
    """Convert a 4x4 transform (canonical face -> camera space) into a HeadPose.

    MediaPipe's metric space is OpenGL-like: x to the image right, y up, z towards the
    viewer, and the canonical face looks along +z. Angles come from where the face's
    forward and up axes point after the rotation, not from an Euler decomposition, so
    yaw and pitch stay meaningful when the head is also rolled (e.g. lying on a sofa).
    """
    rotation = np.asarray(matrix, dtype=np.float64)[:3, :3]
    forward = rotation @ np.array([0.0, 0.0, 1.0])
    up = rotation @ np.array([0.0, 1.0, 0.0])

    yaw = math.degrees(math.atan2(forward[0], forward[2]))
    pitch = math.degrees(math.atan2(forward[1], math.hypot(forward[0], forward[2])))
    roll = math.degrees(math.atan2(up[0], up[1]))
    return HeadPose(yaw=yaw, pitch=pitch, roll=roll)
