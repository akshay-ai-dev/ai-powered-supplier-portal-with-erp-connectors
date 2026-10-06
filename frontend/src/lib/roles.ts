import type { User } from "@/lib/types";

/**
 * How a person's role is shown everywhere. The role itself is one value, "inspector", in two kinds:
 * a company inspector (created by an admin, works on every buyer's shipments) and a buyer's own inspector
 * (created by that buyer under My inspectors, works on that buyer's shipments only).
 */
export function roleLabel(u: Pick<User, "role" | "owner_name">): string {
  if (u.role === "inspector") return u.owner_name ? `Inspector for ${u.owner_name}` : "Inspector (company-wide)";
  return u.role.charAt(0).toUpperCase() + u.role.slice(1);
}
