"use client";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-fetch";
import { ErrorNote, PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TeamMessageThread } from "@/components/team-message-thread";

interface Contact { inspector_id: number; name: string; active: boolean; unread: number }

function ChatPage() {
  const { user } = useAuth();
  const params = useSearchParams();
  const allowed = user?.role === "buyer" || user?.role === "inspector";
  const { data, loading, error } = useFetch<Contact[]>(allowed ? "/api/team/chat" : null);
  const [selected, setSelected] = useState<number | null>(null);
  const requested = selected ?? Number(params?.get("inspector"));
  const contact = data?.find((c) => c.inspector_id === requested) ?? data?.[0];

  if (!allowed) return <ErrorNote message="Chat is available to buyers and their inspectors." />;
  return (
    <>
      <PageHeader title={user?.role === "buyer" ? "Inspector chat" : "Buyer chat"}
        description="Private messages between a buyer and their assigned inspectors." />
      <ErrorNote message={error} />
      {loading && !data && <p className="text-sm text-muted-foreground">Loading conversations…</p>}
      {data?.length === 0 && <p className="text-sm text-muted-foreground">{user?.role === "buyer" ? "Add an inspector under My inspectors to start chatting." : "Chat becomes available when an inspector account belongs to a buyer."}</p>}
      {contact && (
        <div className="grid gap-4 md:grid-cols-[220px_1fr]">
          <nav aria-label="Conversations" className="space-y-2">
            {data?.map((c) => (
              <button key={c.inspector_id} onClick={() => setSelected(c.inspector_id)}
                aria-current={c.inspector_id === contact.inspector_id ? "true" : undefined}
                className={`w-full rounded-md border px-3 py-2 text-left text-sm ${c.inspector_id === contact.inspector_id ? "bg-accent font-medium" : "hover:bg-accent/50"}`}>
                {c.name}{!c.active && <span className="ml-2 text-xs text-muted-foreground">Disabled</span>}
              </button>
            ))}
          </nav>
          <Card>
            <CardHeader><CardTitle>{contact.name}</CardTitle></CardHeader>
            <CardContent><TeamMessageThread key={contact.inspector_id} inspectorId={contact.inspector_id} /></CardContent>
          </Card>
        </div>
      )}
    </>
  );
}

export default function TeamChatPage() {
  return <Suspense fallback={<p className="text-sm text-muted-foreground">Loading conversations…</p>}><ChatPage /></Suspense>;
}
