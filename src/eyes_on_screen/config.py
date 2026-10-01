"""Application configuration: YAML file -> validated, immutable pydantic models."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

DEFAULT_CONFIG_PATH = Path("config.yaml")


class ConfigError(Exception):
    """The config file is missing, unreadable or invalid. The message is user-facing."""


class _Section(BaseModel):
    # extra="forbid" turns a typo in a key into an error instead of a silently ignored setting.
    model_config = ConfigDict(extra="forbid", frozen=True)


class VideoSourceKind(StrEnum):
    RTSP = "rtsp"
    WEBCAM = "webcam"


class FaceLostAction(StrEnum):
    PAUSE = "pause"
    IGNORE = "ignore"


class VideoConfig(_Section):
    source: VideoSourceKind = VideoSourceKind.RTSP
    rtsp_url: str | None = None
    webcam_index: int = Field(default=0, ge=0)
    process_fps: float = Field(default=10.0, gt=0, le=60)
    reconnect_delay_s: float = Field(default=2.0, gt=0)

    @field_validator("rtsp_url")
    @classmethod
    def _check_rtsp_scheme(cls, url: str | None) -> str | None:
        if url is not None and not url.lower().startswith(("rtsp://", "rtsps://")):
            raise ValueError("must start with rtsp:// or rtsps://")
        return url

    @model_validator(mode="after")
    def _check_source_settings(self) -> VideoConfig:
        if self.source is VideoSourceKind.RTSP and not self.rtsp_url:
            raise ValueError("rtsp_url is required when source is 'rtsp'")
        return self


class DetectionConfig(_Section):
    models_dir: Path = Path("models")
    max_faces: int = Field(default=3, ge=1, le=10)
    min_detection_confidence: float = Field(default=0.6, ge=0, le=1)


class TargetConfig(_Section):
    # Normalized [x1, y1, x2, y2]; (0, 0) is the top-left corner of the frame.
    roi: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)

    @field_validator("roi")
    @classmethod
    def _check_roi(
        cls, roi: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = roi
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            raise ValueError(
                "expected [x1, y1, x2, y2] with 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1"
            )
        return roi


class PoseConfig(_Section):
    yaw_center_deg: float = Field(default=0.0, ge=-90, le=90)
    pitch_center_deg: float = Field(default=0.0, ge=-90, le=90)
    yaw_tolerance_deg: float = Field(default=20.0, gt=0, le=90)
    pitch_tolerance_deg: float = Field(default=15.0, gt=0, le=90)


class BehaviorConfig(_Section):
    pause_after_s: float = Field(default=1.5, gt=0)
    resume_after_s: float = Field(default=0.5, gt=0)
    on_face_lost: FaceLostAction = FaceLostAction.PAUSE
    face_lost_after_s: float = Field(default=3.0, gt=0)


class AppleTvConfig(_Section):
    identifier: str | None = None
    credentials_file: Path = Path("data/pyatv.conf")

    @field_validator("identifier", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class LoggingConfig(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    events_file: Path | None = Path("logs/events.log")

    @field_validator("level", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class AppConfig(_Section):
    video: VideoConfig
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    target: TargetConfig = Field(default_factory=TargetConfig)
    pose: PoseConfig = Field(default_factory=PoseConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    apple_tv: AppleTvConfig = Field(default_factory=AppleTvConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    def with_paths_relative_to(self, base_dir: Path) -> AppConfig:
        """Return a copy where every relative path is anchored to `base_dir`."""

        def anchor(path: Path) -> Path:
            return path if path.is_absolute() else (base_dir / path).resolve()

        events_file = self.logging.events_file
        return self.model_copy(
            update={
                "detection": self.detection.model_copy(
                    update={"models_dir": anchor(self.detection.models_dir)}
                ),
                "apple_tv": self.apple_tv.model_copy(
                    update={"credentials_file": anchor(self.apple_tv.credentials_file)}
                ),
                "logging": self.logging.model_copy(
                    update={"events_file": anchor(events_file) if events_file else None}
                ),
            }
        )


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Read and validate the YAML config.

    Relative paths inside the file are resolved against the file's own folder,
    so the app behaves the same regardless of the current working directory.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(
            f"config file not found: {path} (copy config.example.yaml to config.yaml)"
        ) from None
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}:\n{exc}") from exc

    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"invalid config {path}: top level must be a mapping of sections")

    try:
        config = AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path, exc)) from None

    return config.with_paths_relative_to(path.resolve().parent)


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    lines = [f"invalid config {path}:"]
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(f"  - {location}: {error['msg']}")
    return "\n".join(lines)
