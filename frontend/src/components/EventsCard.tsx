import { useT } from "../hooks/useT";
import { eventText } from "../i18n";
import { useEos } from "../store";
import { EventGlyph } from "./icons";

export function EventsCard() {
  const events = useEos((state) => state.events);
  const t = useT();
  return (
    <div className="card">
      <div className="card-head">
        <h2>{t.events.title}</h2>
      </div>
      <ul className="events">
        {events.length ? (
          events.map((event) => {
            const kind = event.level === "warning" ? "warning" : event.kind;
            return (
              <li key={`${event.ts}-${event.text}`} className={`ev-${kind}`}>
                <span className="ev-icon">
                  <EventGlyph kind={kind} />
                </span>
                <span className="ev-text">{eventText(event, t)}</span>
                <span className="ev-time">{event.time}</span>
              </li>
            );
          })
        ) : (
          <li className="empty">{t.events.empty}</li>
        )}
      </ul>
    </div>
  );
}
