"""Picking the viewer to follow among the faces found in the ROI."""

from __future__ import annotations

from collections.abc import Sequence

from eyes_on_screen.vision.analyzer import FaceObservation


def select_target(faces: Sequence[FaceObservation]) -> FaceObservation | None:
    """The largest face: with the camera under the TV, that is the viewer closest to it."""
    return max(faces, key=lambda face: face.area, default=None)
