import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "./api";

function respond(status: number, body?: unknown, statusText = "") {
  const fetchMock = vi.fn(async () =>
    body === undefined
      ? new Response(null, { status, statusText })
      : new Response(typeof body === "string" ? body : JSON.stringify(body), { status, statusText }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("sends settings changes as a JSON PATCH and returns the new settings", async () => {
    const fetchMock = respond(200, { roi: [0, 0, 1, 1] });

    const settings = await api.changeSettings({ behavior: { pause_after_s: 2 } });

    expect(settings).toEqual({ roi: [0, 0, 1, 1] });
    expect(fetchMock).toHaveBeenCalledWith("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: '{"behavior":{"pause_after_s":2}}',
    });
  });

  it("returns nothing for 202 and 204 answers", async () => {
    respond(202);
    await expect(api.calibrate()).resolves.toBeUndefined();
    respond(204);
    await expect(api.press("pause")).resolves.toBeUndefined();
  });

  it("reports a FastAPI string detail", async () => {
    respond(503, { detail: "not connected to the Apple TV" });

    const error = await api.press("play").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(503);
    expect((error as ApiError).message).toBe("not connected to the Apple TV");
  });

  it("joins FastAPI validation issues without the body prefix", async () => {
    respond(422, {
      detail: [{ loc: ["body", "behavior", "pause_after_s"], msg: "Input should be greater than 0" }],
    });

    await expect(api.changeSettings({ behavior: { pause_after_s: 0 } })).rejects.toThrow(
      "behavior.pause_after_s: Input should be greater than 0",
    );
  });

  it("falls back to the status line when the body is not JSON", async () => {
    respond(500, "boom", "Internal Server Error");

    await expect(api.setAutomation(true)).rejects.toThrow("500 Internal Server Error");
  });
});
