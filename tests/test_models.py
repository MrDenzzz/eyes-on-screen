import hashlib
from pathlib import Path

import pytest

from eyes_on_screen.vision.models import (
    ALL_MODELS,
    ModelError,
    ModelFile,
    download_model,
    missing_models,
    require_models,
)

CONTENT = b"model weights"


@pytest.fixture
def model(tmp_path: Path) -> ModelFile:
    source = tmp_path / "upstream" / "weights.bin"
    source.parent.mkdir()
    source.write_bytes(CONTENT)
    return ModelFile(
        filename="weights.bin",
        url=source.as_uri(),
        sha256=hashlib.sha256(CONTENT).hexdigest(),
        description="test model",
    )


def test_downloads_and_then_reuses_a_valid_copy(model, tmp_path):
    models_dir = tmp_path / "models"

    assert download_model(model, models_dir) is True
    assert (models_dir / "weights.bin").read_bytes() == CONTENT
    assert download_model(model, models_dir) is False


def test_corrupted_local_copy_is_replaced(model, tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "weights.bin").write_bytes(b"truncated")

    assert download_model(model, models_dir) is True
    assert (models_dir / "weights.bin").read_bytes() == CONTENT


def test_checksum_mismatch_leaves_no_file_behind(model, tmp_path):
    models_dir = tmp_path / "models"
    tampered = ModelFile(model.filename, model.url, "0" * 64, model.description)

    with pytest.raises(ModelError, match="checksum mismatch"):
        download_model(tampered, models_dir)

    assert list(models_dir.iterdir()) == []


def test_unreachable_source_is_reported(model, tmp_path):
    gone = ModelFile(model.filename, (tmp_path / "nope.bin").as_uri(), model.sha256, "gone")

    with pytest.raises(ModelError, match="cannot download"):
        download_model(gone, tmp_path / "models")


def test_missing_models_are_listed_with_a_hint(tmp_path):
    assert missing_models(tmp_path) == list(ALL_MODELS)
    with pytest.raises(ModelError, match="eos download-models"):
        require_models(tmp_path)
