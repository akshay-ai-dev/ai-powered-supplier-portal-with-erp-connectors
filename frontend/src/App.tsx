import { CommunicationLive } from "@/pages/dev/CommunicationLive";
import { CommunicationPreview } from "@/pages/dev/CommunicationPreview";

export default function App() {
  // Dev-only pages for the communication slice (until the real layout and router exist):
  //   /dev/communication  – components with mock data
  //   /dev/live           – components against the real backend
  if (window.location.pathname === "/dev/communication") return <CommunicationPreview />;
  if (window.location.pathname === "/dev/live") return <CommunicationLive />;

  return (
    <main className="p-4">
      <h1 className="text-2xl font-semibold">{import.meta.env.VITE_APP_NAME}</h1>
    </main>
  );
}
