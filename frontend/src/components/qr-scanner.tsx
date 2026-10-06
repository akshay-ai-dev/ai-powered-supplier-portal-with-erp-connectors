"use client";
import { useEffect, useId, useRef, useState } from "react";
import { Camera, ScanLine, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { unitCodeFromScan } from "@/lib/units";

/**
 * Scan or type a unit code. A USB or Bluetooth barcode scanner types the code and presses Enter into the focused
 * box, so it needs nothing special; the camera button reads the QR code with the device camera instead.
 */
export function QrScanner({ onScan, disabled, placeholder = "Scan a QR code or type the unit code" }: { onScan: (code: string) => void; disabled?: boolean; placeholder?: string }) {
  const [value, setValue] = useState("");
  const [camera, setCamera] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const wrap = useRef<HTMLDivElement>(null); // a wrapper element, so the field can be re-focused without relying on the shared Input forwarding its ref
  const regionId = "qr-" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const latest = useRef(onScan);
  latest.current = onScan;

  useEffect(() => {
    if (!camera) return;
    let stopped = false;
    let scanner: { stop: () => Promise<void>; clear: () => void } | null = null;
    let last = { code: "", at: 0 };
    (async () => {
      try {
        const { Html5Qrcode } = await import("html5-qrcode");
        if (stopped) return;
        const instance = new Html5Qrcode(regionId);
        scanner = instance;
        await instance.start(
          { facingMode: "environment" },
          { fps: 10, qrbox: { width: 220, height: 220 } },
          (text) => {
            const now = Date.now();
            if (text === last.code && now - last.at < 2500) return; // the same label stays in view for a moment
            last = { code: text, at: now };
            latest.current(unitCodeFromScan(text));
          },
          () => {},
        );
      } catch (err) {
        setCameraError(err instanceof Error ? err.message : "The camera could not be started");
        setCamera(false);
      }
    })();
    return () => {
      stopped = true;
      if (scanner) {
        const s = scanner;
        s.stop().then(() => s.clear()).catch(() => {});
      }
    };
  }, [camera, regionId]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const code = unitCodeFromScan(value);
    if (code) latest.current(code);
    setValue("");
    wrap.current?.querySelector("input")?.focus();
  }

  return (
    <div className="space-y-2">
      <form onSubmit={submit} className="flex gap-2">
        <div ref={wrap} className="relative flex-1">
          <ScanLine className="pointer-events-none absolute left-2.5 top-2 size-4 text-muted-foreground" />
          <Input aria-label="Unit code" autoFocus autoComplete="off" spellCheck={false} disabled={disabled} value={value} onChange={(e) => setValue(e.target.value)} placeholder={placeholder} className="pl-8 font-mono" />
        </div>
        <Button type="submit" disabled={disabled || !value.trim()}>
          Go
        </Button>
        <Button type="button" variant="outline" aria-label={camera ? "Stop camera" : "Scan with the camera"} onClick={() => { setCameraError(null); setCamera((c) => !c); }}>
          {camera ? <X className="size-4" /> : <Camera className="size-4" />}
        </Button>
      </form>
      {cameraError && <p className="text-xs text-destructive">{cameraError}. You can still type the code or use a barcode scanner.</p>}
      {camera && <div id={regionId} className="mx-auto w-full max-w-xs overflow-hidden rounded-md border" />}
    </div>
  );
}
