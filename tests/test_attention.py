import pytest

from eyes_on_screen.attention.calibration import CalibrationError, calibrate_center
from eyes_on_screen.attention.classifier import Attention, classify
from eyes_on_screen.config import PoseConfig
from eyes_on_screen.vision.analyzer import FaceObservation
from eyes_on_screen.vision.head_pose import HeadPose
from eyes_on_screen.vision.target import select_target

POSE = PoseConfig(
    yaw_center_deg=5, pitch_center_deg=15, yaw_tolerance_deg=20, pitch_tolerance_deg=10
)


def face(yaw: float | None = 0, pitch: float = 0, box=(0.1, 0.1, 0.2, 0.2)) -> FaceObservation:
    pose = None if yaw is None else HeadPose(yaw=yaw, pitch=pitch, roll=0)
    return FaceObservation(box=box, score=0.9, pose=pose)


class TestClassify:
    def test_no_face_is_absent(self):
        assert classify(None, POSE) is Attention.ABSENT

    def test_face_without_landmarks_is_away(self):
        assert classify(face(yaw=None), POSE) is Attention.AWAY

    @pytest.mark.parametrize(
        ("yaw", "pitch"),
        [(5, 15), (25, 15), (-15, 15), (5, 25), (5, 5), (24, 6)],
    )
    def test_within_tolerance_around_the_calibrated_centre_is_looking(self, yaw, pitch):
        assert classify(face(yaw, pitch), POSE) is Attention.LOOKING

    @pytest.mark.parametrize(
        ("yaw", "pitch"),
        [(26, 15), (-16, 15), (5, 26), (5, 4), (55, 15), (0, 0)],
    )
    def test_outside_tolerance_is_away(self, yaw, pitch):
        assert classify(face(yaw, pitch), POSE) is Attention.AWAY


class TestSelectTarget:
    def test_largest_face_wins(self):
        small = face(box=(0.1, 0.1, 0.15, 0.15))
        large = face(box=(0.5, 0.1, 0.6, 0.2))

        assert select_target([small, large]) is large

    def test_face_with_landmarks_beats_a_larger_one_without(self):
        # e.g. a cat printed on a pillow next to the viewer
        viewer = face(yaw=0, box=(0.1, 0.1, 0.15, 0.15))
        pillow_cat = face(yaw=None, box=(0.5, 0.1, 0.7, 0.3))

        assert select_target([pillow_cat, viewer]) is viewer

    def test_face_without_landmarks_is_used_when_it_is_the_only_one(self):
        turned_away = face(yaw=None)

        assert select_target([turned_away]) is turned_away

    def test_no_faces_no_target(self):
        assert select_target([]) is None


class TestCalibration:
    def test_centre_is_the_median_pose_and_tolerances_are_kept(self):
        poses = [HeadPose(y, p, 0) for y, p in [(2, 14), (3, 15), (4, 16), (40, 50), (3.04, 15)]]

        calibrated = calibrate_center(poses, POSE)

        assert (calibrated.yaw_center_deg, calibrated.pitch_center_deg) == (3.0, 15.0)
        assert calibrated.yaw_tolerance_deg == POSE.yaw_tolerance_deg

    def test_too_few_poses_are_rejected(self):
        with pytest.raises(CalibrationError, match="at least"):
            calibrate_center([HeadPose(0, 0, 0)] * 2, POSE)

    def test_implausible_centre_is_rejected(self):
        with pytest.raises(CalibrationError, match="implausible"):
            calibrate_center([HeadPose(150, 0, 0)] * 5, POSE)
