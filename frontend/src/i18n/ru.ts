import type { EventInfo, Playback } from "../protocol/types";
import type { Dict } from "./en";
import { ruDecimal, ruPlural } from "./plural";

type Params = EventInfo["params"];

const signed = (value: number, digits = 0) => `${value < 0 ? "−" : "+"}${ruDecimal(Math.abs(value), digits)}`;
const seconds = (value: number) => `${ruDecimal(Math.max(0, value), 1)} с`;

const REASONS: Record<string, string> = {
  looked_away: "отвлёкся на",
  no_viewer: "никого нет уже",
  looking: "смотрит на экран уже",
};
const why = (p: Params) => `${REASONS[String(p.reason)] ?? p.reason} ${seconds(Number(p.seconds))}`;
const COMMANDS: Record<string, string> = { pause: "пауза", resume: "продолжение" };
const ACTIONS: Record<string, string> = { pause: "Пауза", play: "Пуск" };

const PLAYBACK: Record<Playback, string> = {
  playing: "играет",
  paused: "на паузе",
  idle: "простаивает",
  loading: "загрузка",
  stopped: "остановлен",
  seeking: "перемотка",
  unknown: "неизвестно",
};

export const ru: Dict = {
  fmt: {
    seconds,
    duration: (value: number) => `${value} с`,
    degrees: (value: number) => `±${value}°`,
    signed,
  },
  playback: PLAYBACK,
  nav: { pages: "Страницы", live: "Наблюдение", record: "Запись", language: "Язык" },
  top: {
    connecting: "подключение…",
    waitingCamera: "ждём камеру",
    stream: (width: number, height: number, fps: string, ms: number) =>
      `${width}×${height} · анализ ${fps.replace(".", ",")} к/с · ${ms} мс`,
    camera: "Камера",
    fps: (fps: number) => `${fps} к/с`,
    reconnecting: "переподключение",
    appleTv: "Apple TV",
    connected: "подключён",
    offline: "не в сети",
    notSetUp: "не настроен",
    dryRun: "Пробный запуск",
    automation: "Автоматика",
    automationTitle: "Когда выключено, ничего не ставится на паузу и не продолжается",
  },
  video: {
    waitingCamera: "Ждём камеру…",
    waitingVideo: "Ждём видео…",
    zone: "Зона",
    zoneTitle: "Нарисуйте область, где сидят зрители",
    calibrate: "Калибровка",
    calibrateTitle: "Посмотрите на экран, чтобы задать, что считается просмотром",
    fullscreen: "Во весь экран",
    zoneHint: "Проведите по видео, чтобы нарисовать зону просмотра",
    save: "Сохранить",
    cancel: "Отмена",
    zoneNotSaved: "Зона не сохранена",
    calibration: "Калибровка",
    lookAtScreen: "Смотрите на экран",
    holdStill: "Не двигайтесь…",
    state: { looking: "СМОТРИТ", away: "ОТВЛЁКСЯ", absent: "НИКОГО" },
    viewingZone: "ЗОНА ПРОСМОТРА",
    ignored: "не зритель",
    noLandmarks: "нет точек лица",
    face: { looking: "Смотрит", away: "Отвлёкся" },
  },
  now: {
    automationOff: "автоматика выключена",
    notConnected: "Apple TV не подключён",
    pausingNow: "ставлю паузу…",
    resumingNow: "снимаю с паузы…",
    skipped: (command: "pause" | "resume") =>
      `пробный запуск · ${command === "pause" ? "поставил бы паузу" : "снял бы с паузы"}, команда не отправлена`,
    pausing: "пауза",
    wouldPause: "была бы пауза",
    resuming: "продолжение",
    wouldResume: "было бы продолжение",
    countdown: (what: string, left: string) => `${what} через ${left}`,
    nobodyHere: (what: string) => `никого нет · ${what}`,
    pausedByEos: "пауза от eos · посмотрите на экран, чтобы продолжить",
    pausedRemote: "пауза с пульта · не трогаю",
    waitingLook: "жду, пока кто-нибудь посмотрит",
    watching: "смотрит",
    player: (playback: string) => `плеер: ${playback}`,
  },
  timeline: {
    title: "Внимание",
    span: "последние 60 секунд",
    looking: "Смотрит",
    away: "Отвлёкся",
    nobody: "Никого",
    now: "сейчас",
    ago: (s: number) => `-${s} с`,
  },
  player: {
    title: "Плеер",
    notSetUp: "Не настроен",
    offline: "не в сети",
    nothingYet: "Пока нет данных",
    watchOnly: "Только наблюдение: подключите Apple TV командой `eos atv pair`",
    nothingPlaying: "Ничего не играет",
    notConnected: "Apple TV не подключён",
    pausedByEos: "Пауза от eos",
    pausedRemote: "Пауза с пульта",
    waitingLook: "Ждёт взгляда",
    pause: "Пауза",
    play: "Пуск",
  },
  viewers: {
    title: "Зрители",
    inZone: (viewers: number, looking: number) => `в зоне: ${viewers} · смотрят: ${looking}`,
    nobody: "В зоне никого",
    ignored: "Не зритель",
    ignoredWhy: "похоже на лицо, но точек лица не было",
    turnedAway: "отвернулся, точек лица нет",
    angles: (yaw: string, pitch: string) => `поворот ${yaw}° · наклон ${pitch}°`,
    eyesDown: "глаза ↓",
    eyesDownTitle: "Взгляд вниз",
    looking: "Смотрит",
    away: "Отвлёкся",
  },
  settings: {
    title: "Настройки",
    waiting: "Ждём eos…",
    saved: "Сохранено",
    notSaved: "Не сохранено",
    severalViewers: "Несколько зрителей",
    modes: { any_away: "Хоть один", all_away: "Все", nearest: "Ближайший" },
    modeHints: {
      any_away: "Пауза, как только кто-то в зоне отвлёкся.",
      all_away: "Играть, пока смотрит хотя бы один зритель.",
      nearest: "Следить только за зрителем, ближайшим к ТВ.",
    },
    pauseAfter: "Пауза, если отвлёкся на",
    resumeAfter: "Продолжить, если смотрит",
    whenNobody: "Когда никого нет",
    faceLost: { pause: "Пауза", ignore: "Играть дальше" },
    after: "…через",
    headPose: "Поза головы",
    screenDirection: "Направление на экран",
    calibrateHint: ["Задаётся кнопкой ", "Калибровка", ", пока вы смотрите на экран."],
    yawTolerance: "Допустимый поворот влево-вправо",
    pitchTolerance: "Допустимый наклон вверх-вниз",
  },
  events: {
    title: "События",
    empty: "Событий пока нет",
    phrases: {
      started: (p: Params) => (p.dry_run ? "запуск (пробный: команды только в логе)" : "запуск"),
      stopped: () => "остановка",
      paused: (p: Params) => `пауза: ${why(p)}`,
      resumed: (p: Params) => `продолжение: ${why(p)}`,
      would_pause: (p: Params) => `была бы пауза: ${why(p)}`,
      would_resume: (p: Params) => `было бы продолжение: ${why(p)}`,
      command_failed: (p: Params) => `${COMMANDS[String(p.command)] ?? p.command}: ошибка — ${p.error}`,
      not_confirmed: (p: Params) =>
        `${COMMANDS[String(p.command)] ?? p.command}: Apple TV не подтвердил, попробую ещё раз`,
      player: (p: Params) => {
        const details = [p.app, p.title].filter(Boolean).join(" - ");
        const playback = PLAYBACK[p.playback as Playback] ?? p.playback;
        return `плеер: ${playback}${details ? ` (${details})` : ""}`;
      },
      player_lost: () => "плеер: связь потеряна",
      paused_elsewhere: () => "пауза не от eos: снимать её не буду",
      started_elsewhere: () => "запустили не через eos: жду, пока кто-нибудь посмотрит",
      automation: (p: Params) => (p.enabled ? "автоматика включена" : "автоматика выключена"),
      pressed: (p: Params) => `нажата кнопка «${ACTIONS[String(p.action)] ?? p.action}»`,
      calibrated: (p: Params) => {
        const poses = Number(p.poses);
        return `калибровка: экран на повороте ${signed(Number(p.yaw), 1)}, наклоне ${signed(Number(p.pitch), 1)} (по ${poses} ${ruPlural(poses, ["позе", "позам", "позам"])})`;
      },
      calibration_failed: (p: Params) => `калибровка не удалась: ${p.error}`,
      recording_started: (p: Params) => `запись в ${p.file}`,
      recording_saved: (p: Params) => `запись сохранена: ${p.file}`,
      step_recorded: (p: Params) => {
        const frames = Number(p.frames);
        return `записан шаг ${p.step}: ${frames} ${ruPlural(frames, ["кадр", "кадра", "кадров"])}, лицо измерено в ${Math.round(Number(p.face_share) * 100)}%`;
      },
    },
  },
  offline: "Связь с eos потеряна. Переподключаюсь…",
  record: {
    title: "Запись взгляда",
    intro:
      "Записывает, как ведут себя голова и глаза на каждом шаге, чтобы подобрать пороги паузы по реальным данным. Сохраняются только числа, без изображений.",
    stepOf: (step: number, total: number) => `Шаг ${step} из ${total}`,
    getReady: "Приготовьтесь",
    recording: "Запись",
    stats: (frames: number, share: string) =>
      `${frames} ${ruPlural(frames, ["кадр", "кадра", "кадров"])} · лицо измерено в ${share}`,
    stopStep: "Остановить шаг",
    start: "Старт",
    redoStep: (step: number) => `Повторить шаг ${step}`,
    finish: "Завершить",
    hint: "После «Старт» есть 5 с, чтобы сесть как нужно. Сигнал отмечает начало, двойной сигнал — конец, так что смотреть на страницу не нужно.",
    allDone: "Все шаги записаны",
    allDoneHint: "Нажмите «Завершить», чтобы закрыть файл. Любой шаг можно переснять из списка.",
    savedTo: "Сохранено в",
    steps: "Шаги",
    progress: (done: number, total: number, minutes: number) =>
      `готово ${done} из ${total} · около ${minutes} мин`,
    face: (share: string) => `лицо ${share}`,
    take: (take: number) => `дубль ${take}`,
    redo: "Переснять",
    redoTitle: "Записать этот шаг заново",
    noFace: "Нет лица",
    nobodyInZone: "в зоне никого",
    faceChip: "Лицо",
    sound: "Звук",
    soundTitle: "Сигналы в начале и в конце шага",
    error: "Запись",
    labels: { screen: "экран", phone: "телефон", elsewhere: "в сторону", closed: "глаза закрыты" },
    stepTexts: {
      watch_tv: { title: "Смотрите ТВ", instruction: "Сядьте как обычно и смотрите телевизор. Моргать и двигаться можно." },
      phone_in_hands: {
        title: "Телефон в руках",
        instruction: "Держите телефон на уровне груди и листайте, как обычно на диване.",
      },
      phone_on_lap: { title: "Телефон на коленях", instruction: "Положите телефон на колени и читайте с него." },
      back_to_tv: { title: "Снова на ТВ", instruction: "Смотрите на телевизор." },
      look_around: {
        title: "Смотрите по сторонам",
        instruction: "Смотрите куда угодно, кроме ТВ: в окно, по сторонам, на соседа.",
      },
      eyes_closed: { title: "Закройте глаза", instruction: "Откиньтесь назад и закройте глаза, как будто задремали." },
      phone_again: { title: "Снова телефон", instruction: "Снова телефон, держите как удобно." },
      tv_once_more: { title: "И снова ТВ", instruction: "Напоследок смотрите телевизор." },
    },
  },
};
