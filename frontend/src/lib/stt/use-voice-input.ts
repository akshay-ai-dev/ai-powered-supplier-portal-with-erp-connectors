"use client";
// Mic button state machine: record with MediaRecorder, decode to mono 16 kHz on the main thread, then
// transcribe in the Moonshine worker. The ~385 MB model loads on the first mic press, not on page load.
import { useCallback, useEffect, useRef, useState } from "react";
import { MODELS_URL } from "@/lib/router/classify";
import type { SttIn, SttOut } from "./moonshine.worker";

const SAMPLE_RATE = 16000;
export type VoiceState = "idle" | "loading" | "recording" | "transcribing";

async function toMono16k(data: ArrayBuffer): Promise<Float32Array> {
  const ac = new AudioContext({ sampleRate: SAMPLE_RATE }); // resamples during decode
  try {
    const buf = await ac.decodeAudioData(data);
    if (buf.numberOfChannels === 1) return buf.getChannelData(0);
    const mono = new Float32Array(buf.length);
    for (let c = 0; c < buf.numberOfChannels; c++) {
      const ch = buf.getChannelData(c);
      for (let i = 0; i < ch.length; i++) mono[i] += ch[i] / buf.numberOfChannels;
    }
    return mono;
  } finally {
    ac.close();
  }
}

export function useVoiceInput(onText: (text: string) => void) {
  const [state, setState] = useState<VoiceState>("idle");
  const [error, setError] = useState<string | null>(null);
  // Live mic level for the waveform while recording; only reads the stream, never touches the transcription path.
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  const worker = useRef<Worker | null>(null);
  const ready = useRef<Promise<void> | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const onTextRef = useRef(onText);
  onTextRef.current = onText;

  useEffect(() => () => worker.current?.terminate(), []);

  const ensureModel = useCallback(() => {
    if (ready.current) return ready.current;
    const w = new Worker(new URL("./moonshine.worker.ts", import.meta.url), { type: "module" });
    worker.current = w;
    ready.current = new Promise<void>((resolve, reject) => {
      w.onmessage = (e: MessageEvent<SttOut>) => {
        if (e.data.type === "ready") resolve();
        else if (e.data.type === "error") reject(new Error(e.data.message));
      };
    });
    ready.current.catch(() => {
      ready.current = null; // allow a retry on the next press
      w.terminate();
    });
    w.postMessage({ type: "init", modelsUrl: new URL(MODELS_URL, location.origin).href } satisfies SttIn);
    return ready.current;
  }, []);

  const transcribe = useCallback(async (pcm: Float32Array) => {
    const w = worker.current!;
    const id = Date.now();
    return new Promise<string>((resolve, reject) => {
      w.onmessage = (e: MessageEvent<SttOut>) => {
        const msg = e.data;
        if (msg.type === "result" && msg.id === id) resolve(msg.text);
        else if (msg.type === "error") reject(new Error(msg.message));
      };
      w.postMessage({ type: "transcribe", id, pcm } satisfies SttIn, [pcm.buffer]);
    });
  }, []);

  const toggle = useCallback(async () => {
    setError(null);
    if (recorder.current) {
      recorder.current.stop();
      return;
    }
    try {
      setState("loading");
      await ensureModel();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const meter = new AudioContext();
      const node = meter.createAnalyser();
      node.fftSize = 512;
      meter.createMediaStreamSource(stream).connect(node);
      setAnalyser(node);
      const chunks: Blob[] = [];
      const rec = new MediaRecorder(stream);
      recorder.current = rec;
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setAnalyser(null);
        meter.close();
        recorder.current = null;
        setState("transcribing");
        try {
          const blob = new Blob(chunks, { type: chunks[0]?.type });
          const text = await transcribe(await toMono16k(await blob.arrayBuffer()));
          if (text) onTextRef.current(text);
          else setError("Didn't catch that. Try again.");
        } catch (e) {
          setError(e instanceof Error ? e.message : "Transcription failed");
        } finally {
          setState("idle");
        }
      };
      rec.start();
      setState("recording");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Microphone unavailable");
      setState("idle");
    }
  }, [ensureModel, transcribe]);

  return { state, error, toggle, analyser };
}
