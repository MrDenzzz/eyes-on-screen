import { useEffect } from "react";

import { AttentionTimeline } from "./components/AttentionTimeline";
import { EventsCard } from "./components/EventsCard";
import { OfflineBanner, Toasts } from "./components/Overlays";
import { PlayerCard } from "./components/PlayerCard";
import { RecordPage } from "./components/RecordPage";
import { SettingsCard } from "./components/SettingsCard";
import { TopBar } from "./components/TopBar";
import { VideoStage } from "./components/VideoStage";
import { ViewersCard } from "./components/ViewersCard";
import { connection } from "./eos";
import { usePage } from "./hooks/usePage";

export function App() {
  const page = usePage();
  useEffect(() => {
    connection.start();
    return () => connection.stop();
  }, []);

  return (
    <>
      <TopBar page={page} />
      {page === "record" ? (
        <RecordPage />
      ) : (
        <main className="layout">
          <section className="stage-col">
            <VideoStage />
            <AttentionTimeline />
          </section>
          <aside className="side-col">
            <PlayerCard />
            <ViewersCard />
            <SettingsCard />
            <EventsCard />
          </aside>
        </main>
      )}
      <Toasts />
      <OfflineBanner />
    </>
  );
}
