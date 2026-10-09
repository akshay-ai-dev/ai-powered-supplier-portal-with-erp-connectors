"use client";
import { useEffect, useState } from "react";
import { ArrowLeft, Mail, RefreshCw } from "lucide-react";
import { dateTime } from "@/lib/api";
import { useFetch } from "@/lib/use-fetch";
import { EMAILS_CHANGED } from "@/lib/use-unread-emails";
import { Button } from "@/components/ui/button";
import { ErrorNote, PageHeader } from "@/components/page-header";

interface EmailSummary {
  id: string;
  subject: string;
  from: string;
  to: string[];
  snippet: string;
  created: string;
  read: boolean;
}
interface EmailFull {
  id: string;
  subject: string;
  from: string;
  to: string[];
  date: string;
  text: string;
}

export default function EmailsPage() {
  const inbox = useFetch<EmailSummary[]>("/api/emails");
  const [selected, setSelected] = useState<string | null>(null);
  const mail = useFetch<EmailFull>(selected ? `/api/emails/${selected}` : null);
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const openedId = mail.data?.id;
  useEffect(() => {
    if (!openedId) return;
    setOpened((s) => (s.has(openedId) ? s : new Set(s).add(openedId)));
    window.dispatchEvent(new Event(EMAILS_CHANGED));
  }, [openedId]);

  return (
    <>
      <PageHeader title="Emails" description="Messages sent to you by the system.">
        <Button variant="outline" size="sm" onClick={() => inbox.reload()}>
          <RefreshCw className="mr-2 size-4" />
          Refresh
        </Button>
      </PageHeader>
      <ErrorNote message={inbox.error} />
      <div className="grid gap-4 md:grid-cols-[minmax(0,360px)_1fr]">
        <div className={`rounded-lg border ${selected ? "hidden md:block" : ""}`}>
          {inbox.loading && !inbox.data && <p className="p-4 text-sm text-muted-foreground">Loading…</p>}
          {inbox.data?.length === 0 && <p className="p-4 text-sm text-muted-foreground">No emails yet.</p>}
          <ul className="divide-y">
                        {inbox.data?.map((m) => {
              const unread = !m.read && !opened.has(m.id);
              return (
                <li key={m.id}>
                  <button
                    onClick={() => setSelected(m.id)}
                    className={`w-full px-4 py-3 text-left transition-colors hover:bg-accent/50 ${selected === m.id ? "bg-accent" : ""}`}
                  >
                    <div className="flex items-center gap-2">
                      {unread && <span className="size-2 shrink-0 rounded-full bg-primary" aria-hidden />}
                      <span className={`truncate text-sm ${unread ? "font-semibold" : "font-medium"}`}>{m.subject || "(no subject)"}</span>
                      {unread && <span className="sr-only">(unread)</span>}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">{m.snippet}</div>
                    <div className="mt-1 text-xs text-muted-foreground">{dateTime(m.created)}</div>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <div className={`rounded-lg border p-5 ${selected ? "" : "hidden md:block"}`}>
          {!selected && (
            <div className="grid h-40 place-items-center text-sm text-muted-foreground">
              <span className="flex items-center gap-2">
                <Mail className="size-4" />
                Select an email to read it
              </span>
            </div>
          )}
          {selected && (
            <>
              <Button variant="ghost" size="sm" className="mb-3 md:hidden" onClick={() => setSelected(null)}>
                <ArrowLeft className="mr-1 size-4" />
                Back
              </Button>
              {mail.loading && !mail.data && <p className="text-sm text-muted-foreground">Loading…</p>}
              <ErrorNote message={mail.error} />
              {mail.data && (
                <article>
                  <h2 className="text-lg font-semibold">{mail.data.subject}</h2>
                  <div className="mt-2 space-y-0.5 text-xs text-muted-foreground">
                    <div>From: {mail.data.from}</div>
                    <div>To: {mail.data.to.join(", ")}</div>
                    <div>{dateTime(mail.data.date)}</div>
                  </div>
                  {/* Plain text only: never render email HTML inside the app */}
                  <pre className="mt-4 whitespace-pre-wrap font-sans text-sm">{mail.data.text}</pre>
                </article>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
