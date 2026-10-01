"""Concrete model backends for FaceAnalyzer: YuNet (OpenCV) and MediaPipe Face Landmarker."""

from __future__ import annotations

from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

from eyes_on_screen.config import DetectionConfig
from eyes_on_screen.vision.analyzer import Box, FaceAnalyzer, Roi
from eyes_on_screen.vision.head_pose import HeadPose, head_pose_from_matrix
from eyes_on_screen.vision.models import FACE_DETECTOR, FACE_LANDMARKER, require_models

_NMS_THRESHOLD = 0.3
_YUNET_SCORE_COLUMN = 14
# Lower than MediaPipe's default 0.5: the crops are upscaled ~4x and slightly blurry.
# At 0.5 a real face turned towards a phone lost its landmarks at most crop sizes.
_LANDMARKER_CONFIDENCE = 0.3


class YuNetDetector:
    """OpenCV's YuNet: runs at the image's own resolution, so faces of ~20 px are found."""

    def __init__(self, model_path: Path, score_threshold: float, top_k: int = 50) -> None:
        self._net = cv2.FaceDetectorYN.create(
            str(model_path), "", (320, 320), score_threshold, _NMS_THRESHOLD, top_k
        )
        self._input_size: tuple[int, int] | None = None

    def __call__(self, image: np.ndarray) -> list[tuple[Box, float]]:
        height, width = image.shape[:2]
        if self._input_size != (width, height):
            self._net.setInputSize((width, height))
            self._input_size = (width, height)
        _, faces = self._net.detect(image)
        if faces is None:
            return []
        # Row: x, y, w, h, 5 landmark points (10 values), score.
        return [(Box(*map(float, row[:4])), float(row[_YUNET_SCORE_COLUMN])) for row in faces]


class LandmarkerPoseEstimator:
    def __init__(self, model_path: Path) -> None:
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=_LANDMARKER_CONFIDENCE,
            min_face_presence_confidence=_LANDMARKER_CONFIDENCE,
            output_facial_transformation_matrixes=True,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

    def __call__(self, crop: np.ndarray) -> HeadPose | None:
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        result = self._landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        if not result.facial_transformation_matrixes:
            return None
        return head_pose_from_matrix(result.facial_transformation_matrixes[0])

    def close(self) -> None:
        self._landmarker.close()


def create_face_analyzer(config: DetectionConfig, roi: Roi) -> FaceAnalyzer:
    """Build the production analyzer; raises ModelError if model files are missing."""
    require_models(config.models_dir)
    return FaceAnalyzer(
        roi,
        YuNetDetector(config.models_dir / FACE_DETECTOR.filename, config.min_detection_confidence),
        LandmarkerPoseEstimator(config.models_dir / FACE_LANDMARKER.filename),
        max_faces=config.max_faces,
    )
