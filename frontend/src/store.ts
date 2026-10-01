import { create } from "zustand";

import { DICTS, eventText, initialLang, type Lang, rememberLang } from "./i18n";
import type { TimelinePoint } from "./lib/timeline";
import type { EventInfo, FrameHeader, StatusMessage } from "./protocol/types";

export const TIMELINE_MS = 60_000;
export const MAX_EVENTS = 100;
const TOAST_MS = 4000;
const FRESH_EVENT_MS = 10_000;

export interface Frame {
  header: FrameHeader;
  bitmap: ImageBitmap;
}

export interface Marker {
  ts: number;
  kind: "pause" | "resume";
}

export interface Toast {
  id: number;
  text: string;
  error: boolean;
}

export interface EosState {
  online: boolean;
  status: StatusMessage | null;
  frame: Frame | null;
  timeline: TimelinePoint[];
  markers: Marker[];
  /** Newest first. */
  events: EventInfo[];
  toasts: Toast[];
  zoneEditing: boolean;
  lang: Lang;
}

export const initialState: EosState = {
  online: false,
  status: null,
  frame: null,
  timeline: [],
  markers: [],
  events: [],
  toasts: [],
  zoneEditing: false,
  lang: initialLang(),
};

export const useEos = create<EosState>()(() => initialState);

export function setOnline(online: boolean): void {
  useEos.setState({ online });
}

export function applyStatus(status: StatusMessage): void {
  useEos.setState({ status });
}

/** Shows a decoded frame unless a newer one already is (decoding is asynchronous). */
export function applyFrame(header: FrameHeader, bitmap: ImageBitmap): void {
  const { frame, timeline, markers } = useEos.getState();
  if (frame && frame.header.seq >= header.seq) {
    bitmap.close();
    return;
  }
  frame?.bitmap.close();
  const cutoff = header.ts - TIMELINE_MS;
  useEos.setState({
    frame: { header, bitmap },
    timeline: [...timeline.filter((p) => p.ts >= cutoff), { ts: header.ts, attention: header.attention }],
    markers: markers.filter((m) => m.ts >= cutoff),
  });
}

export function addEvents(events: EventInfo[]): void {
  if (!events.length) return;
  const state = useEos.getState();
  const markers = events.flatMap((event): Marker[] =>
    event.kind === "pause" || event.kind === "resume" ? [{ ts: event.ts, kind: event.kind }] : [],
  );
  useEos.setState({
    events: [...[...events].reverse(), ...state.events].slice(0, MAX_EVENTS),
    markers: [...state.markers, ...markers],
  });
  for (const event of events) {
    if (event.kind === "calibration" && Date.now() - event.ts < FRESH_EVENT_MS) {
      toast(eventText(event, DICTS[state.lang]), event.level === "warning");
    }
  }
}

let nextToastId = 1;

export function toast(text: string, error = false): void {
  const id = nextToastId++;
  useEos.setState((state) => ({ toasts: [...state.toasts, { id, text, error }] }));
  setTimeout(() => {
    useEos.setState((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  }, TOAST_MS);
}

export function setZoneEditing(zoneEditing: boolean): void {
  useEos.setState({ zoneEditing });
}

export function setLang(lang: Lang): void {
  rememberLang(lang);
  useEos.setState({ lang });
}
