"use client";
import Link from "next/link";
import { use, useEffect, useMemo, useState } from "react";
import QRCode from "qrcode";
import { ArrowLeft, Printer } from "lucide-react";
import { useFetch } from "@/lib/use-fetch";
import type { LabelData } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { unitUrl } from "@/lib/units";
import { ErrorNote, PageHeader } from "@/components/page-header";

const SAVED = "erp_label_base_url";

/** "erp.example.com" becomes https://erp.example.com, "192.168.1.44:3000" becomes http://192.168.1.44:3000. Null if it is not an address. */
function cleanBase(raw: string): string | null {
  let t = raw.trim().replace(/\/+$/, "");
  if (!t) return null;
  if (!/^[a-z]+:\/\//i.test(t)) t = (/^(localhost|\d{1,3}(\.\d{1,3}){3})(:\d+)?$/i.test(t) ? "http://" : "https://") + t;
  try {
    const u = new URL(t);
    return u.protocol === "http:" || u.protocol === "https:" ? u.origin : null;
  } catch {
    return null;
  }
}
const isLocalhost = (base: string) => /^https?:\/\/(localhost|127\.|\[::1\])/i.test(base);

function savedBase(): string {
  try {
    return localStorage.getItem(SAVED) ?? "";
  } catch {
    return "";
  }
}

/**
 * One QR label per unit, laid out for printing. The QR code is a link to the unit page
 * (https://your-domain/units/CODE, or http://192.168.1.44:3000/units/CODE on a local network), so a phone camera opens it.
 */
export default function ShipmentLabelsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, loading } = useFetch<LabelData>(`/api/shipments/${id}/labels`);
  const [images, setImages] = useState<Record<string, string>>({});
  const [typed, setTyped] = useState<string | null>(null);
  const [fallback, setFallback] = useState(""); // what was saved last time, else this page's own address (known only in the browser)
  useEffect(() => setFallback(savedBase() || window.location.origin), []);

  // PUBLIC_APP_URL from the environment is the source of truth. Without it: what was typed or used last time, else this page's own address.
  const fixed = data?.base_url ?? "";
  const input = fixed || (typed ?? fallback);
  const base = useMemo(() => cleanBase(input), [input]);

  useEffect(() => {
    if (!data || !base) return;
    let cancelled = false;
    (async () => {
      const out: Record<string, string> = {};
      for (const u of data.units) out[u.code] = await QRCode.toDataURL(unitUrl(u.code, base), { margin: 1, width: 220, errorCorrectionLevel: "M" });
      if (!cancelled) setImages(out);
    })();
    return () => {
      cancelled = true;
    };
  }, [data, base]);

  function change(value: string) {
    setTyped(value);
    const b = cleanBase(value);
    if (b && !fixed) {
      try {
        localStorage.setItem(SAVED, b);
      } catch {
        /* the address just is not remembered */
      }
    }
  }

  if (loading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (error || !data) return <ErrorNote message={error ?? "Not found"} />;

  return (
    <>
      <div className="print:hidden">
        <Link href={`/shipments/${id}`} className="mb-4 inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="mr-1 size-4" />
          Back to {data.shipment_no}
        </Link>
        <PageHeader title={`QR labels for ${data.shipment_no}`} description={`${data.units.length} labels for order ${data.po_number}. Print them and stick one on each item before shipping. Scanning a label opens that unit in ERP Copilot.`}>
          <Button disabled={!base} onClick={() => window.print()}>
            <Printer className="mr-1 size-4" />
            Print labels
          </Button>
        </PageHeader>

        <div className="mb-4 max-w-2xl space-y-2">
          <Label htmlFor="base">Address in the QR codes</Label>
          <Input id="base" value={input} readOnly={!!fixed} disabled={!!fixed} onChange={(e) => change(e.target.value)} placeholder="https://erp.yourcompany.com" aria-invalid={!base} />
          {!base ? (
            <p className="text-xs text-destructive">Enter an address such as https://erp.yourcompany.com or http://192.168.1.44:3000.</p>
          ) : (
            <p className="text-xs text-muted-foreground">
              Each QR code opens <span className="font-mono">{unitUrl("CODE", base)}</span>. People must sign in, and only an inspector can inspect the unit.
              {fixed ? " The address comes from the PUBLIC_APP_URL setting." : " PUBLIC_APP_URL is not set. Ask an administrator to set it in .env (your domain, or http://192.168.1.44:3000 on a local network); until then you can type the address here."}
            </p>
          )}
          {base && isLocalhost(base) && (
            <p role="alert" className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
              <b>{base}</b> only works on this computer, so a phone cannot open these labels. Replace it with your domain or this computer&apos;s network address (for example <span className="font-mono">http://192.168.1.44:3000</span>), or open ERP Copilot from that address and reload this page.
            </p>
          )}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 print:grid-cols-4 print:gap-2" aria-label="Labels">
        {data.units.map((u) => (
          <div key={u.code} className="break-inside-avoid rounded-md border bg-white p-2 text-center text-black">
            {images[u.code] ? (
              // eslint-disable-next-line @next/next/no-img-element -- a data: URL made in the browser, nothing for next/image to optimise
              <img src={images[u.code]} alt={`QR code for ${u.code}`} className="mx-auto size-32" />
            ) : (
              <div className="mx-auto size-32" />
            )}
            <div className="mt-1 font-mono text-[11px] leading-tight">{u.code}</div>
            <div className="text-[10px] text-neutral-600">{u.item_code} · {data.supplier_name}</div>
          </div>
        ))}
      </div>
    </>
  );
}
