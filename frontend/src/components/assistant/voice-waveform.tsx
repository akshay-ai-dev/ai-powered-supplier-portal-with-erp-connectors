"use client";
// Loudness-driven waveform shown while the mic records: the newest bar on the right is the current volume,
// older bars scroll left. Drawn on a canvas each animation frame, so React does not re-render per frame.
import { useEffect, useRef } from "react";

const BAR_W = 3;
const GAP = 2;
const PAD = 8;
const MAX_BARS = 400;

export function VoiceWaveform({ analyser }: { analyser: AnalyserNode }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    const samples = new Uint8Array(analyser.fftSize);
    const levels: number[] = [];
    let frame = 0;

    const draw = () => {
      const dpr = window.devicePixelRatio || 1;
      const { clientWidth: w, clientHeight: h } = canvas;
      if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
        canvas.width = w * dpr;
        canvas.height = h * dpr;
      }
      // RMS of the latest audio window, boosted so normal speech fills most of the height.
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const s of samples) sum += ((s - 128) / 128) ** 2;
      levels.push(Math.min(1, Math.sqrt(sum / samples.length) * 4));
      if (levels.length > MAX_BARS) levels.shift();

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = getComputedStyle(canvas).color;
      const bars = Math.floor((w - 2 * PAD + GAP) / (BAR_W + GAP));
      const shown = levels.slice(-bars);
      const start = w - PAD - shown.length * (BAR_W + GAP) + GAP; // newest bar sits at the right edge
      shown.forEach((level, i) => {
        const barH = Math.max(2, level * (h - PAD));
        ctx.fillRect(start + i * (BAR_W + GAP), (h - barH) / 2, BAR_W, barH);
      });
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [analyser]);

  return <canvas ref={canvasRef} aria-label="Listening" className="h-8 w-full rounded-md border text-foreground" />;
}
