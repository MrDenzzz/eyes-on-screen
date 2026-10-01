import type { AutomationInfo, AutomationUpdate, SettingsChanges, SettingsInfo } from "./protocol/types";

/** An error the API answered with, phrased for people. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

interface ValidationIssue {
  loc?: (string | number)[];
  msg?: string;
}

/** FastAPI errors: `detail` is a string, or a list of validation issues for a 422. */
async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string | ValidationIssue[] };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((issue) => [issue.loc?.filter((part) => part !== "body").join("."), issue.msg].filter(Boolean).join(": "))
        .join("; ");
    }
  } catch {
    // not JSON: fall through to the status line
  }
  return `${response.status} ${response.statusText}`.trim();
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response));
  if (response.status === 202 || response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** The REST API of `eos run` (OpenAPI docs at /api/docs). */
export const api = {
  changeSettings: (changes: SettingsChanges) => request<SettingsInfo>("PATCH", "/settings", changes),
  calibrate: () => request<void>("POST", "/calibration"),
  setAutomation: (enabled: boolean) =>
    request<AutomationInfo>("PUT", "/automation", { enabled } satisfies AutomationUpdate),
  press: (action: "play" | "pause") => request<void>("POST", `/player/${action}`),
};
