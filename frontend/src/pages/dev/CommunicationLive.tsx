/**
 * Live demo of the communication slice against the REAL backend (not mock data).
 * Open http://localhost:5173/dev/live with the API running.
 *
 * Stand-in for the role picker: choose a demo user, and every API call is sent as that
 * user (X-Portal-User header). Shows the real NotificationBell and MessageThread.
 * Demo flow: supplier sends a message -> switch to the buyer -> bell shows it -> email in
 * Mailpit (http://localhost:8025) -> supplier B cannot open supplier A's thread.
 */
import { useState } from "react";

import { MessageThread } from "@/components/MessageThread";
import { NotificationBell } from "@/components/NotificationBell";

const REQUEST_ID = "REQ-0001";

// Same demo users as backend/app/notifications/directory.py
const USERS = [
  { id: "buyer-1", label: "Buyer – Priya Sharma", supplierId: null },
  { id: "sup-apex", label: "Supplier – Apex Hydraulics", supplierId: "SUP-SAP-01" },
  { id: "sup-delta", label: "Supplier – Delta Precision", supplierId: "SUP-SAP-02" },
  { id: "sup-orion", label: "Supplier – Orion Castings (declined)", supplierId: "SUP-SAP-03" },
  { id: "inspector-1", label: "Inspector – Tom Becker", supplierId: null },
  { id: "admin-1", label: "Admin", supplierId: null },
] as const;

const THREADS = [
  { supplierId: "SUP-SAP-01", label: "Apex Hydraulics" },
  { supplierId: "SUP-SAP-02", label: "Delta Precision" },
  { supplierId: "SUP-SAP-03", label: "Orion Castings (declined)" },
];

export function CommunicationLive() {
  const [userId, setUserId] = useState<string>("sup-apex");
  const [supplierId, setSupplierId] = useState<string>("SUP-SAP-01");
  const [lastLink, setLastLink] = useState<string | null>(null);

  function switchUser(id: string) {
    setUserId(id);
    setLastLink(null);
    const own = USERS.find((u) => u.id === id)?.supplierId;
    if (own) setSupplierId(own); // suppliers start on their own thread
  }

  function openLink(link: string) {
    setLastLink(link);
    const thread = new URL(link, window.location.origin).searchParams.get("thread");
    if (thread) setSupplierId(thread);
  }

  return (
    <div className="min-h-screen bg-muted/30">
      <header className="flex items-center justify-between border-b bg-background px-6 py-3">
        <div>
          <h1 className="text-lg font-semibold">SRS Supplier Portal – communication live demo</h1>
          <p className="text-xs text-muted-foreground">
            Real backend · request {REQUEST_ID} · emails at localhost:8025
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-sm text-muted-foreground" htmlFor="user">
            Signed in as
          </label>
          <select
            id="user"
            className="rounded-md border bg-background px-2 py-1 text-sm"
            value={userId}
            onChange={(e) => switchUser(e.target.value)}
          >
            {USERS.map((u) => (
              <option key={u.id} value={u.id}>
                {u.label}
              </option>
            ))}
          </select>
          <NotificationBell key={userId} userId={userId} onNavigate={openLink} />
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-4 p-6">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted-foreground">Thread:</span>
          {THREADS.map((t) => (
            <button
              key={t.supplierId}
              type="button"
              onClick={() => setSupplierId(t.supplierId)}
              className={
                "rounded-full border px-3 py-1 text-sm " +
                (t.supplierId === supplierId ? "bg-primary text-primary-foreground" : "bg-background")
              }
            >
              {t.label}
            </button>
          ))}
        </div>
        {lastLink && (
          <p className="text-xs text-muted-foreground">Opened from notification: {lastLink}</p>
        )}
        <div className="rounded-lg border bg-background">
          <MessageThread
            key={`${userId}-${supplierId}`}
            requestId={REQUEST_ID}
            supplierId={supplierId}
            userId={userId}
          />
        </div>
      </main>
    </div>
  );
}
