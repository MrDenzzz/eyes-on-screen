import { useT } from "../hooks/useT";
import { useEos } from "../store";

export function Toasts() {
  const toasts = useEos((state) => state.toasts);
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast${toast.error ? " error" : ""}`}>
          {toast.text}
        </div>
      ))}
    </div>
  );
}

export function OfflineBanner() {
  const online = useEos((state) => state.online);
  const everConnected = useEos((state) => state.status !== null);
  const t = useT();
  if (online || !everConnected) return null;
  return (
    <div className="offline" role="status">
      <div className="spinner" />
      {t.offline}
    </div>
  );
}
