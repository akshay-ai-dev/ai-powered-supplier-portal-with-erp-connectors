/**
 * A unit's QR label holds a link (https://host/units/CODE) so a phone camera opens the unit page.
 * Scanners and the in-app camera may return the whole link; this gets the plain unit code back.
 */
export function unitCodeFromScan(text: string): string {
  const t = text.trim();
  if (t.includes("://") || t.startsWith("/")) {
    const path = t.split(/[?#]/)[0].replace(/\/+$/, "");
    const last = path.split("/").pop() ?? "";
    try {
      return decodeURIComponent(last).trim();
    } catch {
      return last.trim();
    }
  }
  return t;
}

/** A dynamic route segment, percent-decoded (a unit code is plain text, but a pasted or scanned link may have encoded it). */
export function decodeSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** The address a label should point to: the configured public address, else the address this browser is on. */
export function unitUrl(code: string, baseUrl?: string): string {
  const base = (baseUrl || (typeof window === "undefined" ? "" : window.location.origin)).replace(/\/+$/, "");
  return `${base}/units/${encodeURIComponent(code)}`;
}
