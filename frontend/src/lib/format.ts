/** "+3", "−12" (a real minus sign), with a fixed number of decimals. */
export function signed(value: number, digits = 0): string {
  return `${value < 0 ? "−" : "+"}${Math.abs(value).toFixed(digits)}`;
}

/** "1.5 s"; negative durations read as "0.0 s". */
export function seconds(value: number): string {
  return `${Math.max(0, value).toFixed(1)} s`;
}

export function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}
