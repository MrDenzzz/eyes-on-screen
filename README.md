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
