/** Same rule as the API: digits with an optional leading +, separators allowed, 7 to 15 digits. Empty is allowed. */
export function phoneError(value: string): string | null {
  const v = value.trim();
  if (v === "") return null;
  if (!/^\+?[0-9 ()./-]+$/.test(v)) return "Phone number may only contain digits, spaces, ( ) - . / and a leading +";
  const digits = v.replace(/\D/g, "").length;
  if (digits < 7 || digits > 15) return "Phone number must have between 7 and 15 digits";
  return null;
}
