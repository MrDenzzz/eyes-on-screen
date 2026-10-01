import numpy as np
import pytest

from eyes_on_screen.vision.analyzer import (
    Box,
    EyeState,
    FaceAnalyzer,
    FaceEstimate,
    FaceObservation,
)
from eyes_on_screen.vision.head_pose import HeadPose

WIDTH, HEIGHT = 200, 100
ROI = (0.25, 0.5, 0.75, 1.0)  # x 50..150, y 50..100 in pixels
SOME_POSE = HeadPose(1, 2, 3)
SOME_EYES = EyeState(look_down=0.6, look_up=0.0, closed=0.1, squint=0.2)
SOME_ESTIMATE = FaceEstimate(SOME_POSE, SOME_EYES)


class FakeDetector:
    def __init__(self, *faces: tuple[Box, float]) -> None:
        self.faces = list(faces)
        self.seen_shapes: list[tuple[int, ...]] = []

    def __call__(self, image: np.ndarray) -> list[tuple[Box, float]]:
        self.seen_shapes.append(image.shape)
        return self.faces


class FakePose:
    def __init__(self, estimate: FaceEstimate | None = SOME_ESTIMATE) -> None:
        self.estimate = estimate
        self.crops: list[np.ndarray] = []

    def __call__(self, crop: np.ndarray) -> FaceEstimate | None:
        self.crops.append(crop)
        return self.estimate


def make_analyzer(detector, pose=None, max_faces=3, crop_size=32) -> FaceAnalyzer:
    return FaceAnalyzer(
        ROI, detector, pose or FakePose(), max_faces=max_faces, crop_scale=1.6, crop_size=crop_size
    )


def frame(value: int = 255) -> np.ndarray:
    return np.full((HEIGHT, WIDTH, 3), value, np.uint8)


def test_detector_only_sees_the_roi():
    detector = FakeDetector()

    make_analyzer(detector).analyze(frame())

    assert detector.seen_shapes == [(50, 100, 3)]


def test_boxes_are_mapped_back_to_normalized_frame_coordinates():
    detector = FakeDetector((Box(10, 5, 20, 10), 0.9))

    [face] = make_analyzer(detector).analyze(frame())

    assert face.box == pytest.approx((0.30, 0.55, 0.40, 0.65))
    assert face.score == 0.9
    assert face.pose == SOME_POSE
    assert face.eyes == SOME_EYES


def test_only_the_most_confident_faces_are_analysed():
    detector = FakeDetector(
        (Box(0, 0, 10, 10), 0.5), (Box(20, 0, 10, 10), 0.9), (Box(40, 0, 10, 10), 0.7)
    )
    pose = FakePose()

    faces = make_analyzer(detector, pose, max_faces=2).analyze(frame())

    assert [f.score for f in faces] == [0.9, 0.7]
    assert len(pose.crops) == 2


def test_face_crop_is_square_centred_and_padded_at_the_edge():
    # A face in the top-left corner of the ROI: its square crop sticks out of the image.
    detector = FakeDetector((Box(0, 0, 10, 10), 0.9))
    pose = FakePose()

    make_analyzer(detector, pose, crop_size=32).analyze(frame(255))

    [crop] = pose.crops
    assert crop.shape == (32, 32, 3)
    assert crop[0, 0].tolist() == [0, 0, 0]  # padding outside the image
    assert crop[16, 16].tolist() == [255, 255, 255]  # the face stays in the centre


def test_missing_landmarks_are_reported_as_no_pose():
    detector = FakeDetector((Box(10, 5, 20, 10), 0.8))

    [face] = make_analyzer(detector, FakePose(None)).analyze(frame())

    assert face.pose is None
    assert face.eyes is None
    assert face.crop is not None


def test_eye_state_averages_both_eyes():
    from eyes_on_screen.vision.backends import eye_state

    scores = {
        "eyeLookDownLeft": 0.6,
        "eyeLookDownRight": 0.4,
        "eyeLookUpLeft": 0.1,
        "eyeLookUpRight": 0.3,
        "eyeBlinkLeft": 0.0,
        "eyeBlinkRight": 0.2,
        "eyeSquintLeft": 0.5,
        "eyeSquintRight": 0.3,
    }

    assert eye_state(scores) == pytest.approx(
        EyeState(look_down=0.5, look_up=0.2, closed=0.1, squint=0.4)
    )
    assert eye_state({"eyeLookDownLeft": 0.6}) is None


def test_observation_geometry():
    face = FaceObservation(box=(0.2, 0.4, 0.4, 0.8), score=1.0, pose=None)

    assert face.center == pytest.approx((0.3, 0.6))
    assert face.area == pytest.approx(0.08)


def test_close_releases_the_models_that_hold_resources():
    closed = []

    class Estimator:
        def __call__(self, crop):
            return None

        def close(self):
            closed.append("estimator")

    analyzer = FaceAnalyzer((0, 0, 1, 1), lambda image: [], Estimator(), max_faces=1)

    analyzer.close()

    assert closed == ["estimator"]
