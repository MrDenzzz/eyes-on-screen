import { decodeFrame } from "./protocol/frame";
import type { EventInfo, EventsMessage, FrameHeader, StatusMessage } from "./protocol/types";

type ServerText = StatusMessage | EventsMessage;

export interface ConnectionListener {
  online(online: boolean): void;
  status(message: StatusMessage): void;
  events(events: EventInfo[]): void;
  frame(header: FrameHeader, jpeg: Uint8Array<ArrayBuffer>): void;
}

/**
 * The push channel from `eos run`: status, events and video frames, reconnecting with
 * backoff. Commands go the other way through the REST API (api.ts).
 */
export class Connection {
  private readonly listener: ConnectionListener;
  private readonly url: string;
  private ws: WebSocket | null = null;
  private retries = 0;
  private stopped = true;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;

  constructor(listener: ConnectionListener, url: string = defaultUrl()) {
    this.listener = listener;
    this.url = url;
  }

  start(): void {
    this.stopped = false;
    this.open();
  }

  stop(): void {
    this.stopped = true;
    clearTimeout(this.retryTimer);
    this.ws?.close();
    this.ws = null;
  }

  private open(): void {
    const ws = new WebSocket(this.url);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => {
      this.retries = 0;
      this.listener.online(true);
    };
    ws.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
      if (typeof event.data === "string") {
        const message = JSON.parse(event.data) as ServerText;
        if (message.type === "status") this.listener.status(message);
        else this.listener.events(message.events);
      } else {
        const { header, jpeg } = decodeFrame(event.data);
        this.listener.frame(header, jpeg);
      }
    };
    ws.onclose = () => {
      if (ws !== this.ws) return; // a socket replaced by stop()/start() (e.g. StrictMode)
      this.listener.online(false);
      if (!this.stopped) {
        const delay = Math.min(5000, 400 * 2 ** this.retries++);
        this.retryTimer = setTimeout(() => this.open(), delay);
      }
    };
    this.ws = ws;
  }
}

function defaultUrl(): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws`;
}
