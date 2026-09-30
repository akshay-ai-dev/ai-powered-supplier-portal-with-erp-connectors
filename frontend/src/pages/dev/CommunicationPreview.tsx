/**
 * Dev-only preview of the Slice 3 components with mock data. No backend needed.
 * Show it by rendering <Slice3Preview /> from App.tsx while you build; don't ship it.
 */
import { useState } from "react";

import {
  type Attachment,
  MessageThreadView,
  type ThreadInfo,
  type ThreadMessage,
} from "@/components/MessageThread";
import { type NotificationItem, NotificationBellView } from "@/components/NotificationBell";

const minsAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

const MOCK_NOTIFICATIONS: NotificationItem[] = [
  { id: 3, event: "new_message", title: "New message on REQ-0007", body: "Apex Hydraulics sent you a message.", link: "/requests/REQ-0007/messages/SUP-SAP-01", read: false, createdAt: minsAgo(2) },
  { id: 2, event: "response_received", title: "New response on REQ-0007", body: "Bolt & Bearing Co submitted a response.", link: "/requests/REQ-0007", read: false, createdAt: minsAgo(45) },
  { id: 1, event: "erp_change_flagged", title: "ERP change flagged on REQ-0009", body: "The requisition changed in SAP. Review and update or cancel.", link: "/requests/REQ-0009", read: true, createdAt: minsAgo(60 * 26) },
];

const THREAD: ThreadInfo = {
  requestId: "REQ-0007",
  supplierId: "SUP-SAP-01",
  supplierName: "Apex Hydraulics",
  invitationStatus: "invited",
  canPost: true,
};

const MOCK_MESSAGES: ThreadMessage[] = [
  {
    id: 1, author: "sup-apex", authorName: "Apex Hydraulics", authorRole: "supplier", sentAt: minsAgo(30),
    text: "Is surface coating required on the pump housing? Sheet 3 doesn't say.",
    attachments: [{ id: 1, fileName: "sheet-3-markup.pdf", fileType: "application/pdf", sizeBytes: 482_000, url: "/attachments/1" }],
  },
  {
    id: 2, author: "buyer-1", authorName: "Priya Sharma", authorRole: "buyer", sentAt: minsAgo(12),
    text: "Yes, epoxy coating per spec SRS-C-12.", attachments: [],
  },
  {
    id: 3, author: "sup-apex", authorName: "Apex Hydraulics", authorRole: "supplier", sentAt: minsAgo(2),
    text: "Can you confirm only epoxy coating is required?", attachments: [],
  },
];

export function CommunicationPreview() {
  const [items, setItems] = useState(MOCK_NOTIFICATIONS);
  const [messages, setMessages] = useState(MOCK_MESSAGES);
  const [lastNav, setLastNav] = useState<string | null>(null);
  const [readOnly, setReadOnly] = useState(false);
  const [failSend, setFailSend] = useState(false);
  const unread = items.filter((n) => !n.read).length;

  async function mockSend(text: string, files: File[]): Promise<string | null> {
    await new Promise((r) => setTimeout(r, 400));
    if (failSend) return "Couldn't send. Try again.";
    const attachments: Attachment[] = files.map((f, i) => ({
      id: Date.now() + i, fileName: f.name, fileType: f.type, sizeBytes: f.size, url: "#",
    }));
    setMessages((m) => [
      ...m,
      { id: Date.now(), author: "buyer-1", authorName: "Priya Sharma", authorRole: "buyer", text, sentAt: new Date().toISOString(), attachments },
    ]);
    return null;
  }

  return (
    <div className="min-h-screen bg-muted/30">
      <header className="flex items-center justify-between border-b bg-background px-6 py-2">
        <span className="text-sm font-medium">Chat Support</span>
        <NotificationBellView
          unreadCount={unread}
          items={items}
          onSelect={(n) => {
            setItems((xs) => xs.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
            setLastNav(n.link);
          }}
          onMarkAllRead={() => setItems((xs) => xs.map((x) => ({ ...x, read: true })))}
        />
      </header>

      <main className="mx-auto max-w-3xl space-y-4 p-6">
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={readOnly} onChange={(e) => setReadOnly(e.target.checked)} />
            Decline buyer response (read-only)
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={failSend} onChange={(e) => setFailSend(e.target.checked)} />
            Enable send failure
          </label>
        </div>
        {lastNav && <p className="text-sm">Bell navigated to: <code>{lastNav}</code></p>}

        <div className="h-[520px]">
          <MessageThreadView
            thread={readOnly ? { ...THREAD, invitationStatus: "declined", canPost: false } : THREAD}
            messages={messages}
            currentUserId="buyer-1"
            onSend={mockSend}
            onDownload={async (a) => alert(`Would download ${a.fileName}`)}
          />
        </div>
      </main>
    </div>
  );
}
