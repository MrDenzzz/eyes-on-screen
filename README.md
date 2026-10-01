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

## Run

```shell
uv run eos run             # headless; Ctrl+C to stop
uv run eos run --debug     # live window: faces, attention, timers, player state
uv run eos run --dry-run   # only log what would be paused / resumed
```

Pause and resume events with their reasons go to `logs/events.log`.

How it decides:

- Pause while playing once the viewers looked away for `behavior.pause_after_s`
  (or nobody is there for `face_lost_after_s`, if `on_face_lost: pause`).
- Resume only a pause it made, once the viewers look back for `resume_after_s`.
  A pause from the remote is never undone.
- After someone starts playback themselves, it waits until a viewer is seen looking
  at the screen before pausing again (listening from the kitchen stays possible).
- Several viewers: `behavior.multiple_viewers` = `any_away` (default), `all_away`
  or `nearest`.

### Web UI

`eos run` also serves a web UI at <http://127.0.0.1:8765>: live video with the viewing
zone, a viewfinder box and gaze arrow per viewer, the attention timeline of the last
minute with pause/resume markers, player state with Play/Pause, settings (several-viewers
mode, timers, pose tolerances), drawing the zone with the mouse, calibration with a
countdown, an automation switch and the event feed. Changes are saved to `config.yaml`
with its comments intact.

To open it from another device (a laptop on the sofa), set `web.host: 0.0.0.0` and a
`web.password`: the page shows a live camera, so it never goes on the network without one.

The UI is a React + TypeScript app in `frontend/` (Vite, zustand, Vitest). Its build is
committed to `src/eyes_on_screen/web/static`, so running eos needs no Node.js. The
WebSocket protocol is defined once, as pydantic models in `web/messages.py`; their JSON
Schema generates the TypeScript types, and a test fails when the two drift apart.

## Development

```shell
uv run pytest && uv run ruff check        # backend
cd frontend
npm ci
npm run dev        # hot-reloading UI on :5173, proxied to a running `eos run`
npm test           # Vitest + Testing Library
npm run gen        # after changing web/messages.py: schema.json + types.ts
npm run build      # rebuild the UI served by eos (commit the result)
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
