import math

import numpy as np
import pytest

from eyes_on_screen.vision.head_pose import head_pose_from_matrix


def _rot_x(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _rot_y(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rot_z(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def transform(yaw: float = 0, pitch: float = 0, roll: float = 0, translation=(0, 0, 0)):
    """4x4 matrix of a face turned by yaw (to image right), pitch (up) and roll."""
    matrix = np.eye(4)
    matrix[:3, :3] = _rot_y(yaw) @ _rot_x(-pitch) @ _rot_z(-roll)
    matrix[:3, 3] = translation
    return matrix


def test_face_looking_into_the_camera_is_zero():
    pose = head_pose_from_matrix(np.eye(4))

    assert (pose.yaw, pose.pitch, pose.roll) == pytest.approx((0, 0, 0))


@pytest.mark.parametrize(
    ("yaw", "pitch"),
    [(30, 0), (-45, 0), (0, 20), (0, -35), (40, -25), (-60, 15)],
)
@pytest.mark.parametrize("roll", [0, 30])
def test_yaw_and_pitch_are_recovered_regardless_of_roll(yaw, pitch, roll):
    pose = head_pose_from_matrix(transform(yaw, pitch, roll))

    assert pose.yaw == pytest.approx(yaw)
    assert pose.pitch == pytest.approx(pitch)


def test_roll_of_an_upright_facing_head():
    assert head_pose_from_matrix(transform(roll=25)).roll == pytest.approx(25)


def test_translation_is_ignored():
    pose = head_pose_from_matrix(transform(20, -10, translation=(5.0, -3.0, -60.0)))

    assert (pose.yaw, pose.pitch) == pytest.approx((20, -10))
