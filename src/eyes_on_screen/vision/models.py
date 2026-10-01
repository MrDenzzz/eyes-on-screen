"""Model files of the vision pipeline: pinned sources, checksums and download."""

from __future__ import annotations

import hashlib
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_CHUNK = 1 << 16


@dataclass(frozen=True, slots=True)
class ModelFile:
    filename: str
    url: str
    sha256: str
    description: str


FACE_DETECTOR = ModelFile(
    filename="face_detection_yunet_2023mar.onnx",
    url="https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    description="YuNet face detector (OpenCV Zoo)",
)
FACE_LANDMARKER = ModelFile(
    filename="face_landmarker.task",
    url="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    sha256="64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
    description="MediaPipe Face Landmarker",
)
ALL_MODELS = (FACE_DETECTOR, FACE_LANDMARKER)


class ModelError(Exception):
    """A model file is missing, corrupted or could not be downloaded. User-facing message."""


def missing_models(models_dir: Path) -> list[ModelFile]:
    return [model for model in ALL_MODELS if not (models_dir / model.filename).is_file()]


def require_models(models_dir: Path) -> None:
    missing = missing_models(models_dir)
    if missing:
        names = ", ".join(model.filename for model in missing)
        raise ModelError(f"missing models in {models_dir}: {names} (run `eos download-models`)")


def download_model(model: ModelFile, models_dir: Path, *, force: bool = False) -> bool:
    """Download `model` into `models_dir`, verifying its checksum.

    Returns False when a valid copy is already there and nothing was downloaded.
    """
    target = models_dir / model.filename
    if not force and target.is_file() and _sha256(target) == model.sha256:
        return False

    models_dir.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(model.url, timeout=60) as response, partial.open("wb") as out:
            while chunk := response.read(_CHUNK):
                digest.update(chunk)
                out.write(chunk)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise ModelError(f"cannot download {model.filename} from {model.url}: {exc}") from exc

    if digest.hexdigest() != model.sha256:
        partial.unlink(missing_ok=True)
        raise ModelError(
            f"checksum mismatch for {model.filename}: the file at {model.url} has changed"
        )
    partial.replace(target)
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()
