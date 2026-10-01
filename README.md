# eyes-on-screen

Pauses Apple TV when a specific viewer looks away from the screen and resumes when they look back.

> Work in progress. A full description, architecture diagram and demo are coming.

## Quick start

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed automatically.

```shell
uv sync
copy config.example.yaml config.yaml   # then edit config.yaml
uv run eos config-check
uv run pytest
```

## Camera

The Xiaomi C400 is read over RTSP re-published by go2rtc: see [docs/go2rtc.md](docs/go2rtc.md).
A local webcam works too (`video.source: webcam`). Check the stream with:

```shell
uv run eos preview
```

## Apple TV

```shell
uv run eos atv scan              # find the Apple TV and its identifier
uv run eos atv pair              # PINs appear on the TV; credentials go to data/pyatv.conf
uv run eos atv status --watch    # live player state from push updates
uv run eos atv pause | play
```

Since tvOS 15 the media remote protocol is tunnelled over AirPlay, so AirPlay (plus
Companion) is what gets paired. The identifier goes into `apple_tv.identifier`; the
device is found by it on every connect, so its IP may change.

## Head pose

```shell
uv run eos download-models   # YuNet + MediaPipe Face Landmarker, checksums verified
uv run eos pose              # live view; c = calibrate, q = quit
uv run eos pose --record logs/poses.csv
```

Faces across a room are only ~50 px wide in a 2560x1440 frame, too small for MediaPipe's
own face detector. So YuNet finds faces inside `target.roi` at full resolution, and each
face is cropped, upscaled and passed to Face Landmarker, whose transformation matrix gives
yaw and pitch relative to the line from the face to the camera.
