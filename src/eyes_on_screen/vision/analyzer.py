"""Two-stage face analysis: find small faces first, then estimate head pose on a zoomed crop.

The sofa is ~4 m from the camera, so a face is only ~50 px wide in a 2560x1440 frame.
MediaPipe's built-in face detector works on a 128-192 px downscaled image and misses
such faces entirely (measured: 0 of 6 frames). So a small-face detector scans the target
area at full resolution, and only a square crop around each face, upscaled, goes to the
landmarker. The pose is then measured relative to the line from the face to the camera,
whatever the face's position in the frame.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

from eyes_on_screen.vision.head_pose import HeadPose

Roi = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class Box:
    """Axis-aligned box in pixels of the image it was found in."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True, slots=True)
class EyeState:
    """Face Landmarker blendshape scores (0..1), averaged over both eyes."""

    look_down: float
    look_up: float
    closed: float
    squint: float


@dataclass(frozen=True, slots=True)
class FaceEstimate:
    """What the landmarker read from one face crop."""

    pose: HeadPose
    eyes: EyeState | None = None


@dataclass(frozen=True, slots=True)
class FaceObservation:
    box: Roi
    """Normalized (x1, y1, x2, y2) in the full frame."""
    score: float
    pose: HeadPose | None
    """None when the face was found but no landmarks were: usually strongly turned or covered."""
    eyes: EyeState | None = None
    crop: np.ndarray | None = field(default=None, repr=False, compare=False)
    """The zoomed face image the pose was estimated on, for debug views."""

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.box
        return (x1 + x2) / 2, (y1 + y2) / 2

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.box
        return (x2 - x1) * (y2 - y1)


FaceDetector = Callable[[np.ndarray], list[tuple[Box, float]]]
"""BGR image -> [(face box, confidence)]."""
FaceEstimator = Callable[[np.ndarray], FaceEstimate | None]
"""BGR face crop -> head pose and eyes, or None when no face landmarks were found."""


class FaceAnalyzer:
    def __init__(
        self,
        roi: Roi,
        detect_faces: FaceDetector,
        estimate_face: FaceEstimator,
        *,
        max_faces: int,
        crop_scale: float = 1.6,
        crop_size: int = 256,
    ) -> None:
        """`crop_scale`: crop side relative to the face box. On a real, strongly turned
        face 1.6 kept landmarks even at MediaPipe's default confidence; 2.2 and 3.0 lost
        them there."""
        self._roi = roi
        self._detect_faces = detect_faces
        self._estimate_face = estimate_face
        self._max_faces = max_faces
        self._crop_scale = crop_scale
        self._crop_size = crop_size

    @property
    def roi(self) -> Roi:
        return self._roi

    @roi.setter
    def roi(self, roi: Roi) -> None:
        # A plain attribute swap: the analysis thread sees either the old or the new ROI.
        self._roi = roi

    def analyze(self, image: np.ndarray) -> list[FaceObservation]:
        height, width = image.shape[:2]
        roi = self._roi
        x0, y0, x1, y1 = _roi_to_pixels(roi, width, height)
        area = image[y0:y1, x0:x1]

        found = sorted(self._detect_faces(area), key=lambda item: item[1], reverse=True)
        observations = []
        for box, score in found[: self._max_faces]:
            crop = self._face_crop(area, box)
            estimate = self._estimate_face(crop)
            observations.append(
                FaceObservation(
                    box=(
                        (x0 + box.x) / width,
                        (y0 + box.y) / height,
                        (x0 + box.x + box.w) / width,
                        (y0 + box.y + box.h) / height,
                    ),
                    score=score,
                    pose=estimate.pose if estimate else None,
                    eyes=estimate.eyes if estimate else None,
                    crop=crop,
                )
            )
        return observations

    def _face_crop(self, image: np.ndarray, box: Box) -> np.ndarray:
        """Square crop centred on the face, padded with black where it leaves the image.

        Padding instead of shifting keeps the face in the centre, which the pose
        estimate assumes.
        """
        side = max(1, round(self._crop_scale * max(box.w, box.h)))
        left = round(box.x + box.w / 2 - side / 2)
        top = round(box.y + box.h / 2 - side / 2)
        height, width = image.shape[:2]

        x0, y0 = max(left, 0), max(top, 0)
        x1, y1 = min(left + side, width), min(top + side, height)
        crop = image[y0:y1, x0:x1]
        crop = cv2.copyMakeBorder(
            crop,
            top=y0 - top,
            bottom=top + side - y1,
            left=x0 - left,
            right=left + side - x1,
            borderType=cv2.BORDER_CONSTANT,
            value=(0, 0, 0),
        )
        return cv2.resize(crop, (self._crop_size, self._crop_size), interpolation=cv2.INTER_CUBIC)


def _roi_to_pixels(roi: Roi, width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = roi
    return round(x1 * width), round(y1 * height), round(x2 * width), round(y2 * height)
