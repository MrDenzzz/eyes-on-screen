import { Connection } from "./connection";
import { addEvents, applyFrame, applyStatus, setOnline, toast } from "./store";

/** The app's single push connection, feeding the store. */
export const connection = new Connection({
  online: setOnline,
  status: applyStatus,
  events: addEvents,
  frame(header, jpeg) {
    createImageBitmap(new Blob([jpeg], { type: "image/jpeg" }))
      .then((bitmap) => applyFrame(header, bitmap))
      .catch(() => undefined); // a broken frame is simply skipped
  },
});

/** Runs an API call; on failure shows `what: reason` and resolves to false. */
export async function run(call: Promise<unknown>, what: string): Promise<boolean> {
  try {
    await call;
    return true;
  } catch (error) {
    toast(`${what}: ${(error as Error).message}`, true);
    return false;
  }
}
