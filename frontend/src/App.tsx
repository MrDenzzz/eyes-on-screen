import { useEffect } from "react";

import { AttentionTimeline } from "./components/AttentionTimeline";
import { EventsCard } from "./components/EventsCard";
import { OfflineBanner, Toasts } from "./components/Overlays";
import { PlayerCard } from "./components/PlayerCard";
import { SettingsCard } from "./components/SettingsCard";
import { TopBar } from "./components/TopBar";
import { VideoStage } from "./components/VideoStage";
import { ViewersCard } from "./components/ViewersCard";
import { connection } from "./eos";

export function App() {
  useEffect(() => {
    connection.start();
    return () => connection.stop();
  }, []);

  return (
    <>
      <TopBar />
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
      <Toasts />
      <OfflineBanner />
    </>
  );
}
