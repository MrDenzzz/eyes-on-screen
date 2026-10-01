import { useEos } from "../store";
import { EventGlyph } from "./icons";

export function EventsCard() {
  const events = useEos((state) => state.events);
  return (
    <div className="card">
      <div className="card-head">
        <h2>Events</h2>
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
                <span className="ev-text">{event.text}</span>
                <span className="ev-time">{event.time}</span>
              </li>
            );
          })
        ) : (
          <li className="empty">No events yet</li>
        )}
      </ul>
    </div>
  );
}
