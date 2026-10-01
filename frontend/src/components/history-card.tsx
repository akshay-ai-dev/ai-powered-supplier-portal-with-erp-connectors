import { dateTime } from "@/lib/api";
import { AgentBadge, type HistoryEntry } from "@/components/agent-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function HistoryCard({ history }: { history?: HistoryEntry[] }) {
  if (!history) return null;
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>History</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {history.length === 0 && <p className="text-sm text-muted-foreground">No recorded actions.</p>}
        {history.map((h, i) => (
          <div key={i} className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="flex flex-wrap items-center gap-2">
              <b className="capitalize">{h.action}</b>
              {h.detail && <span className="text-muted-foreground">{h.detail}</span>}
              {h.user_name && <span className="text-muted-foreground">by {h.user_name}</span>}
              <AgentBadge channel={h.channel} />
            </span>
            <span className="text-xs text-muted-foreground">{dateTime(h.created_at)}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
