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

Start it and keep the window open:

```powershell
cd go2rtc
.\go2rtc.exe
```

go2rtc reads `go2rtc.yaml` from the current folder; the log shows `config path=...` and
`[api] listen addr=127.0.0.1:1984`. The example config keeps every port on `127.0.0.1`.

## 2. Add the camera

1. Open <http://127.0.0.1:1984>, then **Add > Xiaomi** and log in with your Mi Home account.
   A verification code (email or phone) or a captcha may be requested.
2. go2rtc saves the account token to `go2rtc.yaml` under `xiaomi:`. The file is git-ignored;
   never share or commit it.
3. Load the cameras of the account and add the C400 as a stream named `c400`. go2rtc builds
   the URL; it looks like this:

   ```yaml
   streams:
     c400: xiaomi://<user_id>:<region>@<camera_ip>?did=<device_id>&model=chuangmi.camera.039a04
   ```

   `model` tells which revision you have (`039a04` or `039c04`).

## 3. Check the stream

1. In the go2rtc WebUI, open the `c400` stream. Browser playback of HEVC depends on the
   browser and GPU, so a black player there does not prove the stream is broken.
2. With ffplay (part of the ffmpeg build):

   ```powershell
   ffplay -rtsp_transport tcp rtsp://127.0.0.1:8554/c400
   ```

3. With the app: in `config.yaml` set `video.rtsp_url: "rtsp://127.0.0.1:8554/c400"`, then

   ```powershell
   uv run eos preview
   ```

   The window shows resolution, codec, measured fps and reconnects.

A few `Could not find ref with POC` lines right after connecting are expected: the decoder
joined in the middle of a GOP and outputs grey, smeared frames until the next key frame.
A steady flow of these messages is the problem described below.

## 4. If the HEVC stream is unstable (039a04)

Symptoms from #2030: stutter, a continuous flow of `Could not find ref with POC` or
`Error constructing the frame RPS`. Try in this order:

1. Check the version: `.\go2rtc.exe -version` must print 1.9.14 or newer.
2. Lower the quality: append `&subtype=sd` to the stream URL. Per the go2rtc docs,
   `subtype` accepts `hd`, `sd`, `auto` or `0-5`; the default is 2, and some newer cameras
   have HD at 3.
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
