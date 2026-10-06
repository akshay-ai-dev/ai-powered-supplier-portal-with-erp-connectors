// If NEXT_PUBLIC_API_URL is unset, call the backend on the same host the page was loaded from (port 8000),
// so the app works from localhost and from other machines on the network alike.
export const apiBase = () => process.env.NEXT_PUBLIC_API_URL || (typeof window === "undefined" ? "http://localhost:8000" : `${location.protocol}//${location.hostname}:8000`);
const TOKEN_KEY = "erp_token";

export const tokenStore = {
  get: () => (typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY)),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function errorMessage(body: unknown): string {
  const detail = (body as { detail?: unknown })?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => String(d.msg ?? d).replace(/^Value error, /, "")).join("; ");
  return "Request failed";
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const token = tokenStore.get();
  const res = await fetch(`${apiBase()}${path}`, {
    method: init.method ?? (init.body ? "POST" : "GET"),
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: init.body ? JSON.stringify(init.body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    if (res.status === 401 && token) {
      tokenStore.clear();
      if (typeof window !== "undefined" && !location.pathname.startsWith("/login")) {
        // an expired session on a deep link (a scanned unit page) comes back to that page after signing in again
        const here = location.pathname + location.search;
        location.href = location.pathname === "/" || location.pathname === "/dashboard" ? "/login" : `/login?next=${encodeURIComponent(here)}`;
      }
    }
    throw new ApiError(res.status, errorMessage(data));
  }
  return data as T;
}

/** This browser's offset from UTC in minutes, east positive. Sent with "today" views so that today means the user's own day. */
export function tzMinutes(): number {
  return -new Date().getTimezoneOffset();
}

export const money = (n: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
export const shortDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
export const dateTime = (iso: string) => new Date(iso).toLocaleString();

export async function uploadFile<T>(path: string, file: File): Promise<T> {
  const token = tokenStore.get();
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${apiBase()}${path}`, { method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : {}, body: form });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, errorMessage(data));
  return data as T;
}

/** Downloads through fetch so the bearer token is sent, then hands the blob to the browser. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const token = tokenStore.get();
  const res = await fetch(`${apiBase()}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(res.status, errorMessage(text ? JSON.parse(text) : null));
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export const fileSize = (n: number) => (n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`);

/** "in 2d 3h", "in 45m" or "closed" for a quote deadline. */
export function deadlineLabel(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "No deadline";
  const ms = new Date(iso).getTime() - now;
  if (ms <= 0) return "Closed";
  const mins = Math.floor(ms / 60000);
  const d = Math.floor(mins / 1440);
  const h = Math.floor((mins % 1440) / 60);
  if (d > 0) return `in ${d}d ${h}h`;
  if (h > 0) return `in ${h}h ${mins % 60}m`;
  return `in ${mins}m`;
}

/** Value for <input type="datetime-local"> in the user's own time zone. */
export function toLocalInput(d: Date | string | null | undefined): string {
  if (!d) return "";
  const date = typeof d === "string" ? new Date(d) : d;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** The API stores UTC; a datetime-local string is local time, so convert through Date. */
export const localInputToIso = (v: string): string | null => (v ? new Date(v).toISOString() : null);
