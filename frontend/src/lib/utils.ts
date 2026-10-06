import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Where to go after signing in: only a path on this site. It must start with a single "/" (so not "//host" or "/\host",
 * which browsers read as another site) and hold no control characters; anything else becomes the fallback.
 */
export function safeNext(raw: string | null | undefined, fallback = "/dashboard"): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return fallback;
  for (const ch of raw) if (ch.charCodeAt(0) < 32 || ch.charCodeAt(0) === 127) return fallback;
  return raw.startsWith("/login") || raw.startsWith("/register") ? fallback : raw;
}
