/** Inline SVG icons; stroke icons follow `currentColor`. */

export function Logo() {
  return (
    <svg className="logo" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M2 16C6 8.5 10.7 5 16 5s10 3.5 14 11c-4 7.5-8.7 11-14 11S6 23.5 2 16z" className="logo-eye" />
      <rect x="12" y="11" width="3" height="10" rx="1" className="logo-bar" />
      <rect x="17" y="11" width="3" height="10" rx="1" className="logo-bar" />
    </svg>
  );
}

export function ZoneIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4" />
    </svg>
  );
}

export function TargetIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="3" />
      <path d="M12 1v3M12 20v3M1 12h3M20 12h3" />
    </svg>
  );
}

export function FullscreenIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 4H4v5M15 4h5v5M20 15v5h-5M4 15v5h5" />
    </svg>
  );
}

export function PauseIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="6" y="5" width="4" height="14" rx="1" />
      <rect x="14" y="5" width="4" height="14" rx="1" />
    </svg>
  );
}

export function PlayIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 5l12 7-12 7z" />
    </svg>
  );
}

/** Small filled glyphs for the events feed. */
export function EventGlyph({ kind }: { kind: string }) {
  switch (kind) {
    case "pause":
      return (
        <svg viewBox="0 0 12 12" aria-hidden="true">
          <rect x="2" y="1.5" width="3" height="9" rx="1" />
          <rect x="7" y="1.5" width="3" height="9" rx="1" />
        </svg>
      );
    case "resume":
      return (
        <svg viewBox="0 0 12 12" aria-hidden="true">
          <path d="M3 1.5l7.5 4.5L3 10.5z" />
        </svg>
      );
    case "player":
      return (
        <svg viewBox="0 0 12 12" aria-hidden="true">
          <rect x="1" y="2" width="10" height="7" rx="1.5" />
          <rect x="4" y="10" width="4" height="1.2" rx=".6" />
        </svg>
      );
    case "warning":
      return (
        <svg viewBox="0 0 12 12" aria-hidden="true">
          <rect x="5.2" y="1.5" width="1.6" height="6" rx=".8" />
          <circle cx="6" cy="9.8" r="1" />
        </svg>
      );
    default:
      return (
        <svg viewBox="0 0 12 12" aria-hidden="true">
          <circle cx="6" cy="6" r="2.2" />
        </svg>
      );
  }
}
