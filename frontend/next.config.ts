import type { NextConfig } from "next";

// Cross-origin isolation for the AI Assistant only: it lets the browser models (served from /models) run
// multi-threaded WASM. Workers and ORT's thread workers are separate scripts, so they need COEP too.
const coep = { key: "Cross-Origin-Embedder-Policy", value: "require-corp" };

const nextConfig: NextConfig = {
  output: "standalone",
  async headers() {
    return [
      { source: "/assistant", headers: [{ key: "Cross-Origin-Opener-Policy", value: "same-origin" }, coep] },
      { source: "/_next/static/:path*", headers: [coep] },
      { source: "/models/:path*", headers: [coep] },
    ];
  },
};

export default nextConfig;
