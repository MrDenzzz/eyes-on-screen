"use strict";

// Talks to `eos run` over one WebSocket: binary messages are video frames (4-byte header
// length, JSON header with the analysis of that frame, JPEG), text messages are JSON.

const COLORS = {
  looking: "#3ecf8e",
  away: "#f5a524",
  absent: "#8b95a7",
  ignored: "#8b95a7",
  accent: "#7c8cff",
};
const STATE_LABEL = { looking: "Looking", away: "Away", absent: "Nobody" };
const VIEWER_MODES = {
  any_away: "Pause as soon as anyone in the zone looks away.",
  all_away: "Keep playing while at least one viewer watches.",
  nearest: "Follow only the viewer closest to the TV.",
};
const TIMELINE_S = 60;
const MAX_EVENTS = 100;
const ICONS = {
  pause: '<svg viewBox="0 0 12 12"><rect x="2" y="1.5" width="3" height="9" rx="1"/><rect x="7" y="1.5" width="3" height="9" rx="1"/></svg>',
  resume: '<svg viewBox="0 0 12 12"><path d="M3 1.5l7.5 4.5L3 10.5z"/></svg>',
  player: '<svg viewBox="0 0 12 12"><rect x="1" y="2" width="10" height="7" rx="1.5"/><rect x="4" y="10" width="4" height="1.2" rx=".6"/></svg>',
  warning: '<svg viewBox="0 0 12 12"><rect x="5.2" y="1.5" width="1.6" height="6" rx=".8"/><circle cx="6" cy="9.8" r="1"/></svg>',
  other: '<svg viewBox="0 0 12 12"><circle cx="6" cy="6" r="2.2"/></svg>',
};

const $ = (id) => document.getElementById(id);

const app = {
  ws: null,
  retry: 0,
  nextId: 1,
  pending: new Map(),
  status: null,
  frame: null, // { header, bitmap }
  timeline: [], // { ts, attention }
  markers: [], // { ts, kind }
  viewport: null, // where the video sits on the canvas
  zone: { editing: false, draft: null, start: null },
  busy: new Set(), // controls the user is changing; status updates leave them alone
};

// ---------------------------------------------------------------- connection

function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => {
    app.retry = 0;
    $("offline").hidden = true;
  };
  ws.onmessage = (event) => {
    if (typeof event.data === "string") onText(JSON.parse(event.data));
    else onFrame(event.data);
  };
  ws.onclose = () => {
    $("offline").hidden = false;
    for (const request of app.pending.values()) request.reject(new Error("connection lost"));
    app.pending.clear();
    setTimeout(connect, Math.min(5000, 400 * 2 ** app.retry++));
  };
  app.ws = ws;
}

function send(cmd, body = {}) {
  return new Promise((resolve, reject) => {
    if (!app.ws || app.ws.readyState !== WebSocket.OPEN) {
      reject(new Error("not connected"));
      return;
    }
    const id = app.nextId++;
    app.pending.set(id, { resolve, reject });
    app.ws.send(JSON.stringify({ id, cmd, ...body }));
  });
}

function onText(message) {
  if (message.type === "status") onStatus(message);
  else if (message.type === "events") message.events.forEach((event) => addEvent(event, true));
  else if (message.type === "reply") {
    const request = app.pending.get(message.id);
    if (!request) return;
    app.pending.delete(message.id);
    if (message.ok) request.resolve(message);
    else request.reject(new Error(message.error || "request failed"));
  }
}

// ---------------------------------------------------------------- frames

async function onFrame(buffer) {
  const length = new DataView(buffer).getUint32(0);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 4, length)));
  let bitmap;
  try {
    bitmap = await createImageBitmap(new Blob([new Uint8Array(buffer, 4 + length)], { type: "image/jpeg" }));
  } catch {
    return;
  }
  // Decoding is asynchronous: a newer frame may already be on screen.
  if (app.frame && app.frame.header.seq >= header.seq) {
    bitmap.close();
    return;
  }
  if (app.frame) app.frame.bitmap.close();
  app.frame = { header, bitmap };
  app.timeline.push({ ts: header.ts, attention: header.attention });
  const cutoff = header.ts - TIMELINE_S * 1000;
  while (app.timeline.length && app.timeline[0].ts < cutoff) app.timeline.shift();
  while (app.markers.length && app.markers[0].ts < cutoff) app.markers.shift();

  $("video-empty").hidden = true;
  drawVideo();
  renderViewers(header.faces);
  drawTimeline();
}

// ---------------------------------------------------------------- video canvas

function fitCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return { ctx, width, height };
}

function drawVideo() {
  const { ctx, width, height } = fitCanvas($("video"));
  if (!app.frame) return;
  const { bitmap, header } = app.frame;
  const scale = Math.min(width / bitmap.width, height / bitmap.height);
  const vw = bitmap.width * scale;
  const vh = bitmap.height * scale;
  const view = { x: (width - vw) / 2, y: (height - vh) / 2, w: vw, h: vh };
  app.viewport = view;
  ctx.drawImage(bitmap, view.x, view.y, view.w, view.h);

  const roi = app.zone.editing ? app.zone.draft || currentRoi() : currentRoi();
  if (roi) drawZone(ctx, view, roi, app.zone.editing);
  if (!app.zone.editing) header.faces.forEach((face) => drawFace(ctx, view, face));
}

function currentRoi() {
  return app.status ? app.status.settings.roi : null;
}

function drawZone(ctx, view, roi, editing) {
  const [x1, y1, x2, y2] = roi;
  const r = { x: view.x + x1 * view.w, y: view.y + y1 * view.h, w: (x2 - x1) * view.w, h: (y2 - y1) * view.h };
  ctx.save();
  ctx.fillStyle = editing ? "rgba(5, 7, 12, 0.66)" : "rgba(5, 7, 12, 0.5)";
  ctx.beginPath();
  ctx.rect(view.x, view.y, view.w, view.h);
  ctx.rect(r.x, r.y, r.w, r.h);
  ctx.fill("evenodd");
  ctx.setLineDash(editing ? [] : [7, 6]);
  ctx.lineWidth = editing ? 2 : 1.3;
  ctx.strokeStyle = editing ? COLORS.accent : "rgba(124, 140, 255, 0.75)";
  ctx.strokeRect(r.x, r.y, r.w, r.h);
  ctx.setLineDash([]);
  chip(ctx, "VIEWING ZONE", r.x + 8, r.y + 8, "rgba(124, 140, 255, 0.92)", "#fff", "top");
  if (editing) {
    ctx.fillStyle = COLORS.accent;
    for (const [hx, hy] of [[r.x, r.y], [r.x + r.w, r.y], [r.x, r.y + r.h], [r.x + r.w, r.y + r.h]]) {
      ctx.beginPath();
      ctx.arc(hx, hy, 5, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

function drawFace(ctx, view, face) {
  const [x1, y1, x2, y2] = face.box;
  const b = { x: view.x + x1 * view.w, y: view.y + y1 * view.h, w: (x2 - x1) * view.w, h: (y2 - y1) * view.h };
  ctx.save();
  if (face.state === "ignored") {
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(139, 149, 167, 0.7)";
    ctx.strokeRect(b.x, b.y, b.w, b.h);
    ctx.setLineDash([]);
    chip(ctx, "ignored", b.x, b.y - 6, "rgba(20, 23, 32, 0.85)", "#8b95a7", "bottom");
    ctx.restore();
    return;
  }

  const color = COLORS[face.state];
  const pad = Math.max(4, b.w * 0.12);
  const box = { x: b.x - pad, y: b.y - pad, w: b.w + 2 * pad, h: b.h + 2 * pad };
  const arm = Math.max(7, Math.min(box.w, box.h) * 0.28);
  ctx.strokeStyle = color;
  ctx.lineWidth = face.focus ? 3 : 2;
  ctx.lineCap = "round";
  ctx.shadowColor = "rgba(0, 0, 0, 0.5)";
  ctx.shadowBlur = 6;
  ctx.beginPath();
  for (const [cx, cy, dx, dy] of [
    [box.x, box.y, 1, 1], [box.x + box.w, box.y, -1, 1],
    [box.x, box.y + box.h, 1, -1], [box.x + box.w, box.y + box.h, -1, -1],
  ]) {
    ctx.moveTo(cx, cy + dy * arm);
    ctx.lineTo(cx, cy);
    ctx.lineTo(cx + dx * arm, cy);
  }
  ctx.stroke();
  ctx.shadowBlur = 0;

  if (face.yaw !== null) {
    // Where the face points: right for +yaw, up for +pitch.
    const cx = b.x + b.w / 2;
    const cy = b.y + b.h / 2;
    const length = Math.max(26, b.w * 1.9);
    const ex = cx + length * Math.sin((face.yaw * Math.PI) / 180);
    const ey = cy - length * Math.sin((face.pitch * Math.PI) / 180);
    arrow(ctx, cx, cy, ex, ey, color);
  }

  const angles = face.yaw === null ? "no landmarks" : `${signed(face.yaw)}° / ${signed(face.pitch)}°`;
  chip(ctx, `${STATE_LABEL[face.state]} · ${angles}`, box.x, box.y - 6, color, "#0b0d12", "bottom");
  ctx.restore();
}

function arrow(ctx, x1, y1, x2, y2, color) {
  const angle = Math.atan2(y2 - y1, x2 - x1);
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 2;
  ctx.globalAlpha = 0.9;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - 9 * Math.cos(angle - 0.45), y2 - 9 * Math.sin(angle - 0.45));
  ctx.lineTo(x2 - 9 * Math.cos(angle + 0.45), y2 - 9 * Math.sin(angle + 0.45));
  ctx.closePath();
  ctx.fill();
  ctx.globalAlpha = 1;
}

function chip(ctx, text, x, y, background, color, anchor) {
  ctx.font = "600 11.5px 'Segoe UI Variable Text', 'Segoe UI', system-ui, sans-serif";
  const width = ctx.measureText(text).width + 14;
  const height = 20;
  const top = anchor === "bottom" ? y - height : y;
  ctx.fillStyle = background;
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(x, top, width, height, 6);
  else ctx.rect(x, top, width, height);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.textBaseline = "middle";
  ctx.fillText(text, x + 7, top + height / 2 + 0.5);
}

// ---------------------------------------------------------------- timeline

function drawTimeline() {
  const { ctx, width, height } = fitCanvas($("timeline"));
  const now = app.frame ? app.frame.header.ts : Date.now();
  const start = now - TIMELINE_S * 1000;
  const x = (ts) => ((ts - start) / (TIMELINE_S * 1000)) * width;
  const barTop = 16;
  const barHeight = 22;

  ctx.fillStyle = "rgba(255, 255, 255, 0.04)";
  roundRect(ctx, 0, barTop, width, barHeight, 6);

  ctx.save();
  ctx.beginPath();
  roundRectPath(ctx, 0, barTop, width, barHeight, 6);
  ctx.clip();
  // One rectangle per run of equal attention: per-frame rectangles would overlap at
  // their edges and show stripes. A gap in the video ends a run and stays empty.
  const points = app.timeline;
  let run = null;
  const flush = (end) => {
    if (!run) return;
    ctx.fillStyle = COLORS[run.attention];
    ctx.globalAlpha = run.attention === "absent" ? 0.4 : 0.95;
    ctx.fillRect(x(run.start), barTop, Math.max(1, x(end) - x(run.start)), barHeight);
    run = null;
  };
  for (let i = 0; i < points.length; i++) {
    const point = points[i];
    const next = i + 1 < points.length ? points[i + 1].ts : now;
    if (run && run.attention !== point.attention) flush(point.ts);
    if (!run) run = { attention: point.attention, start: point.ts };
    if (next - point.ts > 1500) flush(point.ts + 100);
  }
  flush(now);
  ctx.restore();
  ctx.globalAlpha = 1;

  for (const marker of app.markers) {
    if (marker.ts < start) continue;
    const mx = x(marker.ts);
    const color = marker.kind === "pause" ? COLORS.away : COLORS.looking;
    ctx.fillStyle = color;
    ctx.fillRect(mx - 1, barTop - 4, 2, barHeight + 8);
    ctx.beginPath();
    ctx.arc(mx, barTop - 7, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.fillStyle = "#5b6375";
  ctx.font = "11px 'Cascadia Mono', ui-monospace, monospace";
  ctx.textBaseline = "top";
  for (let s = 0; s <= TIMELINE_S; s += 10) {
    const tx = width - (s / TIMELINE_S) * width;
    const label = s === 0 ? "now" : `-${s}s`;
    const textWidth = ctx.measureText(label).width;
    ctx.fillText(label, Math.min(Math.max(tx - textWidth / 2, 0), width - textWidth), barTop + barHeight + 6);
  }
}

function roundRectPath(ctx, x, y, w, h, r) {
  if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
  else ctx.rect(x, y, w, h);
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  roundRectPath(ctx, x, y, w, h, r);
  ctx.fill();
}

// ---------------------------------------------------------------- status

function onStatus(status) {
  app.status = status;
  const { stream, player, room, machine, automation, calibration, settings, analysis } = status;

  setPill("pill-camera", "camera-text",
    stream.connected ? "ok" : "warn",
    stream.connected ? `${Math.round(stream.fps)} fps` : "reconnecting");
  setPill("pill-tv", "tv-text",
    player.connected ? "ok" : "bad",
    player.connected ? player.name || "connected" : "offline");
  $("brand-sub").textContent = stream.connected
    ? `${stream.width}×${stream.height} · ${analysis.fps.toFixed(1)} fps analysed · ${Math.round(analysis.ms)} ms`
    : stream.error || "waiting for the camera";
  if (!stream.connected && !app.frame) $("video-empty-text").textContent = "Waiting for the camera…";

  $("dry-badge").hidden = !automation.dry_run;
  if (!app.busy.has("automation")) $("automation").checked = automation.enabled;

  renderNow(status);
  renderPlayer(player, machine);
  renderSettings(settings);
  renderCalibration(calibration);
  $("viewers-summary").textContent = room.viewers
    ? `${room.viewers} in the zone · ${room.looking} looking`
    : "";
  if (app.zone.editing || !app.frame) drawVideo();
}

function setPill(pillId, textId, level, text) {
  const pill = $(pillId);
  pill.classList.remove("ok", "warn", "bad");
  pill.classList.add(level);
  $(textId).textContent = text;
}

function renderNow(status) {
  const { room, machine, automation, player, settings } = status;
  const behavior = settings.behavior;
  const attention = room.attention;
  const streak = machine.streak_s;
  const playing = player.playback === "playing";
  const paused = player.playback === "paused";
  let detail = "";
  let progress = 0;

  if (!automation.enabled) detail = "automation is off";
  else if (!player.connected) detail = "Apple TV not connected";
  else if (machine.pending) detail = machine.pending === "pause" ? "pausing…" : "resuming…";
  else if (playing && machine.armed && attention === "away") {
    progress = streak / behavior.pause_after_s;
    detail = `pausing in ${seconds(behavior.pause_after_s - streak)}`;
  } else if (playing && machine.armed && attention === "absent" && behavior.on_face_lost === "pause") {
    progress = streak / behavior.face_lost_after_s;
    detail = `nobody here · pausing in ${seconds(behavior.face_lost_after_s - streak)}`;
  } else if (paused && machine.paused_by_us && attention === "looking") {
    progress = streak / behavior.resume_after_s;
    detail = `resuming in ${seconds(behavior.resume_after_s - streak)}`;
  } else if (paused && machine.paused_by_us) detail = "paused by eos · look at the screen to resume";
  else if (paused) detail = "paused from the remote · left alone";
  else if (playing && !machine.armed) detail = "waiting for someone to look";
  else if (playing) detail = attention === "looking" ? "watching" : "";
  else if (player.playback) detail = `player ${player.playback}`;

  const label = $("now-state");
  label.textContent = (STATE_LABEL[attention] || "–").toUpperCase();
  $("now").className = `now state-${attention}`;
  $("now-detail").textContent = detail;
  $("now-bar").style.width = `${Math.round(Math.min(1, Math.max(0, progress)) * 100)}%`;
}

function renderPlayer(player, machine) {
  $("player-device").textContent = player.name || "";
  $("player-state").textContent = player.connected ? player.playback || "unknown" : "offline";
  $("player-title").textContent = player.title || (player.connected ? "Nothing playing" : "Apple TV not connected");
  $("player-app").textContent = player.app || "";

  const badges = [];
  if (player.playback === "paused") {
    badges.push(machine.paused_by_us
      ? '<span class="badge badge-accent">Paused by eos</span>'
      : '<span class="badge">Paused from the remote</span>');
  }
  if (player.playback === "playing" && !machine.armed) {
    badges.push('<span class="badge badge-warn">Waiting for a look</span>');
  }
  $("player-badges").innerHTML = badges.join("");
  $("btn-pause").disabled = !player.connected || player.playback !== "playing";
  $("btn-play").disabled = !player.connected || player.playback !== "paused";
}

function renderViewers(faces) {
  const list = $("viewers");
  if (!faces.length) {
    list.innerHTML = '<li class="empty">Nobody in the zone</li>';
    return;
  }
  const order = { looking: 0, away: 1, ignored: 2 };
  list.innerHTML = [...faces]
    .sort((a, b) => order[a.state] - order[b.state])
    .map((face) => {
      if (face.state === "ignored") {
        return `<li><span class="chip state-absent">Ignored</span>
          <span class="viewer-angles">face-like print, never had landmarks</span><span></span></li>`;
      }
      const angles = face.yaw === null
        ? "turned away, no landmarks"
        : `yaw ${signed(face.yaw)}° · pitch ${signed(face.pitch)}°`;
      const eyes = face.eyes_down === null ? "" :
        `<span class="eyes" title="Eyes looking down">eyes ↓<span class="eyes-meter"><i style="width:${Math.round(face.eyes_down * 100)}%"></i></span></span>`;
      return `<li><span class="chip state-${face.state}">${STATE_LABEL[face.state]}</span>
        <span class="viewer-angles">${angles}</span>${eyes}</li>`;
    })
    .join("");
}

function renderSettings(settings) {
  const behavior = settings.behavior;
  setSegmented("seg-viewers", behavior.multiple_viewers);
  $("viewers-hint").textContent = VIEWER_MODES[behavior.multiple_viewers] || "";
  setSegmented("seg-lost", behavior.on_face_lost);
  $("row-lost-delay").hidden = behavior.on_face_lost !== "pause";

  for (const input of document.querySelectorAll("input[type=range][data-section]")) {
    if (!app.busy.has(input.id)) input.value = settings[input.dataset.section][input.dataset.key];
    updateRange(input);
  }
  const pose = settings.pose;
  $("out-centre").textContent = `yaw ${signed(pose.yaw_center_deg, 1)}° · pitch ${signed(pose.pitch_center_deg, 1)}°`;
}

function setSegmented(id, value) {
  for (const button of $(id).querySelectorAll("button")) {
    button.classList.toggle("on", button.dataset.value === value);
  }
}

function updateRange(input) {
  const min = Number(input.min);
  const max = Number(input.max);
  const value = Number(input.value);
  input.style.setProperty("--fill", `${((value - min) / (max - min)) * 100}%`);
  const output = {
    "rng-pause": ["out-pause", seconds(value)],
    "rng-resume": ["out-resume", seconds(value)],
    "rng-lost": ["out-lost", seconds(value)],
    "rng-yaw": ["out-yaw", `±${value}°`],
    "rng-pitch": ["out-pitch", `±${value}°`],
  }[input.id];
  if (output) $(output[0]).textContent = output[1];
}

function renderCalibration(calibration) {
  const overlay = $("calib");
  if (!calibration) {
    overlay.hidden = true;
    $("btn-calibrate").classList.remove("active");
    return;
  }
  overlay.hidden = false;
  $("btn-calibrate").classList.add("active");
  const counting = calibration.phase === "countdown";
  $("calib-count").textContent = counting ? Math.ceil(calibration.remaining_s) : "●";
  $("calib-text").textContent = counting ? "Look at the screen" : "Hold still…";
  const fraction = 1 - calibration.remaining_s / calibration.phase_s;
  $("calib-arc").style.strokeDashoffset = String(327 * (1 - Math.min(1, Math.max(0, fraction))));
}

// ---------------------------------------------------------------- events

function addEvent(event, fromServer) {
  const list = $("events");
  const empty = list.querySelector(".empty");
  if (empty) empty.remove();
  const kind = event.level === "warning" ? "warning" : event.kind;
  const item = document.createElement("li");
  item.className = `ev-${kind}`;
  item.innerHTML = `<span class="ev-icon">${ICONS[kind] || ICONS.other}</span>
    <span class="ev-text"></span><span class="ev-time">${event.time}</span>`;
  item.querySelector(".ev-text").textContent = event.text;
  list.prepend(item);
  while (list.children.length > MAX_EVENTS) list.lastChild.remove();

  if (event.kind === "pause" || event.kind === "resume") {
    app.markers.push({ ts: event.ts, kind: event.kind });
    drawTimeline();
  }
  if (fromServer && event.kind === "calibration" && Date.now() - event.ts < 10000) toast(event.text);
}

// ---------------------------------------------------------------- controls

function toast(text, isError = false) {
  const element = document.createElement("div");
  element.className = `toast${isError ? " error" : ""}`;
  element.textContent = text;
  $("toasts").append(element);
  setTimeout(() => element.remove(), 4000);
}

function flashSaved() {
  const saved = $("saved");
  saved.classList.add("show");
  clearTimeout(flashSaved.timer);
  flashSaved.timer = setTimeout(() => saved.classList.remove("show"), 1500);
}

async function saveChanges(changes) {
  try {
    await send("set", { changes });
    flashSaved();
  } catch (error) {
    toast(`Not saved: ${error.message}`, true);
  }
}

function wireRange(input) {
  let timer = null;
  input.addEventListener("input", () => {
    app.busy.add(input.id);
    updateRange(input);
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const { section, key } = input.dataset;
      await saveChanges({ [section]: { [key]: Number(input.value) } });
      app.busy.delete(input.id);
    }, 350);
  });
}

function wireSegmented(id, section, key) {
  $(id).addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    setSegmented(id, button.dataset.value);
    saveChanges({ [section]: { [key]: button.dataset.value } });
  });
}

function zonePoint(event) {
  const rect = $("video").getBoundingClientRect();
  const view = app.viewport;
  const x = (event.clientX - rect.left - view.x) / view.w;
  const y = (event.clientY - rect.top - view.y) / view.h;
  return [Math.min(1, Math.max(0, x)), Math.min(1, Math.max(0, y))];
}

function setZoneEditing(editing) {
  app.zone = { editing, draft: null, start: null };
  $("zone-bar").hidden = !editing;
  $("zone-save").disabled = true;
  $("btn-zone").classList.toggle("active", editing);
  $("video-wrap").classList.toggle("editing", editing);
  drawVideo();
}

function wireZoneEditor() {
  const canvas = $("video");
  canvas.addEventListener("pointerdown", (event) => {
    if (!app.zone.editing || !app.viewport) return;
    canvas.setPointerCapture(event.pointerId);
    app.zone.start = zonePoint(event);
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!app.zone.editing || !app.zone.start) return;
    const [ax, ay] = app.zone.start;
    const [bx, by] = zonePoint(event);
    app.zone.draft = [Math.min(ax, bx), Math.min(ay, by), Math.max(ax, bx), Math.max(ay, by)];
    const [x1, y1, x2, y2] = app.zone.draft;
    $("zone-save").disabled = x2 - x1 < 0.03 || y2 - y1 < 0.03;
    drawVideo();
  });
  canvas.addEventListener("pointerup", () => {
    app.zone.start = null;
  });
  $("btn-zone").addEventListener("click", () => setZoneEditing(!app.zone.editing));
  $("zone-cancel").addEventListener("click", () => setZoneEditing(false));
  $("zone-save").addEventListener("click", async () => {
    const roi = app.zone.draft.map((value) => Math.round(value * 1000) / 1000);
    await saveChanges({ target: { roi } });
    setZoneEditing(false);
  });
}

function init() {
  document.querySelectorAll("input[type=range][data-section]").forEach(wireRange);
  wireSegmented("seg-viewers", "behavior", "multiple_viewers");
  wireSegmented("seg-lost", "behavior", "on_face_lost");
  wireZoneEditor();

  $("automation").addEventListener("change", async (event) => {
    app.busy.add("automation");
    try {
      await send("automation", { enabled: event.target.checked });
    } catch (error) {
      toast(error.message, true);
    }
    app.busy.delete("automation");
  });
  $("btn-calibrate").addEventListener("click", async () => {
    try {
      await send("calibrate");
    } catch (error) {
      toast(`Calibration: ${error.message}`, true);
    }
  });
  for (const action of ["play", "pause"]) {
    $(`btn-${action}`).addEventListener("click", async () => {
      try {
        await send("player", { action });
      } catch (error) {
        toast(`${action}: ${error.message}`, true);
      }
    });
  }
  $("btn-fullscreen").addEventListener("click", () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else $("video-wrap").requestFullscreen?.();
  });

  new ResizeObserver(() => {
    drawVideo();
    drawTimeline();
  }).observe($("video-wrap"));
  window.addEventListener("resize", drawTimeline);
  drawTimeline();
  connect();
}

// ---------------------------------------------------------------- formatting

function signed(value, digits = 0) {
  const text = Math.abs(value).toFixed(digits);
  return `${value < 0 ? "−" : "+"}${text}`;
}

function seconds(value) {
  return `${Math.max(0, value).toFixed(1)} s`;
}

init();
