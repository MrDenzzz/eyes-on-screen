import { decodeFrame } from "./protocol/frame";
import type {
  EventInfo,
  EventsMessage,
  FrameHeader,
  PageCommand,
  ReplyMessage,
  StatusMessage,
} from "./protocol/types";

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
/** A page command without its id: the connection numbers requests itself. */
export type Command = DistributiveOmit<PageCommand, "id">;

type ServerText = StatusMessage | EventsMessage | ReplyMessage;

export interface ConnectionListener {
  online(online: boolean): void;
  status(message: StatusMessage): void;
  events(events: EventInfo[]): void;
  frame(header: FrameHeader, jpeg: Uint8Array<ArrayBuffer>): void;
}

interface Pending {
  resolve(): void;
  reject(error: Error): void;
}

/** The one WebSocket to `eos run`: reconnects with backoff, turns replies into promises. */
export class Connection {
  private readonly listener: ConnectionListener;
  private readonly url: string;
  private readonly pending = new Map<number, Pending>();
  private ws: WebSocket | null = null;
  private retries = 0;
  private nextId = 1;
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

  send(command: Command): Promise<void> {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("not connected to eos"));
    }
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ ...command, id }));
    });
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
        this.handleText(JSON.parse(event.data) as ServerText);
      } else {
        const { header, jpeg } = decodeFrame(event.data);
        this.listener.frame(header, jpeg);
      }
    };
    ws.onclose = () => {
      if (ws !== this.ws) return; // a socket replaced by stop()/start() (e.g. StrictMode)
      this.listener.online(false);
      for (const request of this.pending.values()) request.reject(new Error("connection lost"));
      this.pending.clear();
      if (!this.stopped) {
        const delay = Math.min(5000, 400 * 2 ** this.retries++);
        this.retryTimer = setTimeout(() => this.open(), delay);
      }
    };
    this.ws = ws;
  }

  private handleText(message: ServerText): void {
    switch (message.type) {
      case "status":
        this.listener.status(message);
        break;
      case "events":
        this.listener.events(message.events);
        break;
      case "reply": {
        const request = message.id === null ? undefined : this.pending.get(message.id);
        if (!request) break;
        this.pending.delete(message.id as number);
        if (message.ok) request.resolve();
        else request.reject(new Error(message.error ?? "request failed"));
        break;
      }
    }
  }
}

function defaultUrl(): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/ws`;
}
