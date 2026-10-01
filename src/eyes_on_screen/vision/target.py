"""Picking the viewer to follow among the faces found in the ROI."""

from __future__ import annotations

from collections.abc import Sequence

from eyes_on_screen.vision.analyzer import FaceObservation


def select_target(faces: Sequence[FaceObservation]) -> FaceObservation | None:
    """The largest face, preferring faces that Face Landmarker confirmed.

    YuNet alone also fires on face-like prints (cats on a sofa pillow, seen live), and
    those never get human face landmarks. If a pillow face were picked over a real
    viewer, it would read as "looking away" and pause the show. An unconfirmed face is
    only used when there is nothing better: a viewer turned far away can lose landmarks.
    With the camera under the TV, the largest face is the viewer closest to it.
    """
    confirmed = [face for face in faces if face.pose is not None]
    return max(confirmed or faces, key=lambda face: face.area, default=None)
