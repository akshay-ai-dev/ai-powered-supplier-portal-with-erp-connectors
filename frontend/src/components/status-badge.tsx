import { Badge } from "@/components/ui/badge";

const styles: Record<string, string> = {
  Draft: "bg-muted text-muted-foreground",
  Pending: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  Approved: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  Closed: "bg-slate-500/15 text-slate-700 dark:text-slate-300",
  "Not Shipped": "bg-muted text-muted-foreground",
  "In Transit": "bg-sky-500/15 text-sky-700 dark:text-sky-400",
  Open: "bg-sky-500/15 text-sky-700 dark:text-sky-400",
  "Quotes closed": "bg-orange-500/15 text-orange-700 dark:text-orange-400",
  Quoted: "bg-violet-500/15 text-violet-700 dark:text-violet-400",
  Awarded: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  Cancelled: "bg-destructive/15 text-destructive",
  Submitted: "bg-violet-500/15 text-violet-700 dark:text-violet-400",
  Accepted: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  Rejected: "bg-destructive/15 text-destructive",
  Shipped: "bg-sky-500/15 text-sky-700 dark:text-sky-400",
  Arrived: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  Delivered: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  Received: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  OK: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  Faulty: "bg-destructive/15 text-destructive",
  Missing: "bg-orange-500/15 text-orange-700 dark:text-orange-400",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={`border-transparent ${styles[status] ?? ""}`}>
      {status}
    </Badge>
  );
}
