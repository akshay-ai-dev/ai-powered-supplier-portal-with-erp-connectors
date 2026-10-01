import { Bot } from "lucide-react";

const LABELS: Record<string, string> = {
  mcp: "AI agent (MCP)",
  "agent-api": "AI agent (API)",
  assistant: "Assistant",
};

/** Shown only for actions that did not come from the normal web UI. */
export function AgentBadge({ channel, compact = false }: { channel?: string | null; compact?: boolean }) {
  if (!channel || channel === "web") return null;
  return (
    <span
      title={`Created or changed through ${LABELS[channel] ?? channel}`}
      className="inline-flex items-center gap-1 rounded-full bg-violet-500/15 px-2 py-0.5 text-xs font-medium text-violet-700 dark:text-violet-400"
    >
      <Bot className="size-3" />
      {compact ? "AI" : (LABELS[channel] ?? channel)}
    </span>
  );
}

export interface HistoryEntry {
  action: string;
  detail: string;
  channel: string;
  created_at: string;
  user_name: string | null;
}
