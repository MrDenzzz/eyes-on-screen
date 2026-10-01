# Xiaomi C400 to RTSP with go2rtc (Windows)

The Xiaomi Smart Camera C400 has no RTSP output. [go2rtc](https://github.com/AlexxIT/go2rtc)
connects to Mi Home cameras over the local network and re-publishes the video as RTSP,
which eyes-on-screen reads.

Before you start:

- The [`xiaomi` source](https://github.com/AlexxIT/go2rtc/blob/master/internal/xiaomi/README.md)
  appeared in go2rtc v1.9.13. **Use v1.9.14 or newer**: its changelog includes
  "Improve cs2+udp proto for xiaomi source #2026 #2030", and
  [#2030](https://github.com/AlexxIT/go2rtc/issues/2030) is the report about C400
  (`chuangmi.camera.039a04`) stuttering with HEVC decoding errors.
- Both C400 revisions are in the
  [known cameras list](https://github.com/AlexxIT/go2rtc/issues/1982):
  `chuangmi.camera.039a04` (2022) and `chuangmi.camera.039c04` (2024), both over the `cs2`
  protocol. The video is HEVC (H.265).
- go2rtc needs Internet access every time it connects to the camera (to fetch encryption
  keys). The video itself stays in the local network.

## 1. Install

From the repository root (check the [releases page](https://github.com/AlexxIT/go2rtc/releases)
for a newer version):

```powershell
Invoke-WebRequest https://github.com/AlexxIT/go2rtc/releases/download/v1.9.14/go2rtc_win64.zip -OutFile go2rtc\go2rtc_win64.zip
Expand-Archive go2rtc\go2rtc_win64.zip -DestinationPath go2rtc
Remove-Item go2rtc\go2rtc_win64.zip
Copy-Item go2rtc\go2rtc.example.yaml go2rtc\go2rtc.yaml
```

For the first setup, start it by hand and keep the window open:

```powershell
cd go2rtc
.\go2rtc.exe
```

go2rtc reads `go2rtc.yaml` from the current folder; the log shows `config path=...` and
`[api] listen addr=127.0.0.1:1984`. The example config keeps every port on `127.0.0.1`.

Afterwards there is no need to start it yourself: with `go2rtc.autostart: true` in
`config.yaml`, every `eos` command that reads the camera starts go2rtc in the background
(unless one is already running), restarts it if it crashes and stops it on exit. Its
output goes to `logs/go2rtc.log`.

## 2. Add the camera

1. Open <http://127.0.0.1:1984>, then **Add > Xiaomi** and log in with your Mi Home account.
   A verification code (email or phone) or a captcha may be requested.
2. go2rtc saves the account token to `go2rtc.yaml` under `xiaomi:`. The file is git-ignored;
   never share or commit it.
3. Load the cameras of the account and add the C400 as a stream named `c400`. go2rtc builds
   the URL; it looks like this:

   ```yaml
   streams:
     c400: xiaomi://<user_id>:<region>@<camera_ip>?did=<device_id>&model=chuangmi.camera.039c04&subtype=3
   ```

   `model` tells which revision you have (`039a04` or `039c04`).
4. Append `&subtype=3` to the generated URL. With the default quality the C400
   (`039c04`) streams only 864x480, far too small for faces across the room; `subtype=3`
   gives 2560x1440 HEVC at 20 fps. The go2rtc docs note that newer cameras keep HD at 3.
5. Give the camera a fixed IP in the router (DHCP reservation by MAC): the IP is part of
   the URL, and the stream breaks if the camera gets a new address.

## 3. Check the stream

1. In the go2rtc WebUI, open the `c400` stream. Browser playback of HEVC depends on the
   browser and GPU, so a black player there does not prove the stream is broken.
2. With ffplay (part of the ffmpeg build):

   ```powershell
   ffplay -rtsp_transport tcp rtsp://127.0.0.1:8554/c400
   ```

3. With the app: in `config.yaml` set `video.rtsp_url: "rtsp://127.0.0.1:8554/c400"`, then

   ```powershell
   uv run eos run --dry-run
   ```

   The web UI at <http://127.0.0.1:8765> shows the video, its resolution and measured fps;
   connects and reconnects are logged to the console.

A few `Could not find ref with POC` lines right after connecting are expected: the decoder
joined in the middle of a GOP and outputs grey, smeared frames until the next key frame.
A steady flow of these messages is the problem described below.

## 4. If the HEVC stream is unstable (039a04)

Symptoms from #2030: stutter, a continuous flow of `Could not find ref with POC` or
`Error constructing the frame RPS`. Try in this order:

1. Check the version: `.\go2rtc.exe -version` must print 1.9.14 or newer.
2. Lower the quality: replace `subtype=3` with `subtype=sd`. Per the go2rtc docs,
   `subtype` accepts `hd`, `sd`, `auto` or `0-5`; the default is 2. Faces get smaller,
   so detection range suffers.
3. Re-encode to H.264 on the NVIDIA GPU: uncomment `c400_h264` in `go2rtc.yaml` and set
   `video.rtsp_url: "rtsp://127.0.0.1:8554/c400_h264"`. This needs ffmpeg in `PATH`.
   It fixes decoding trouble on the app side, but cannot restore packets lost between the
   camera and go2rtc.
4. Fall back to a local webcam: `video.source: webcam`.

## Security notes

- The WebUI holds your Mi Home session, so the example binds it to `127.0.0.1`. go2rtc
  skips authorization for localhost requests even when `username`/`password` are set
  (unless `api.local_auth: true`).
- To reach the WebUI from another device, set `api.username`/`api.password` and change
  `api.listen` consciously; do not expose port 1984 outside your home network.
