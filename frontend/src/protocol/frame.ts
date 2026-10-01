import type { FrameHeader } from "./types";

export interface DecodedFrame {
  header: FrameHeader;
  jpeg: Uint8Array<ArrayBuffer>;
}

/**
 * A binary WebSocket message: 4-byte big-endian header length, the JSON header with the
 * analysis of this very frame, then the JPEG (see eyes_on_screen/web/protocol.py).
 */
export function decodeFrame(buffer: ArrayBuffer): DecodedFrame {
  const length = new DataView(buffer).getUint32(0);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, 4, length))) as FrameHeader;
  return { header, jpeg: new Uint8Array(buffer, 4 + length) };
}
