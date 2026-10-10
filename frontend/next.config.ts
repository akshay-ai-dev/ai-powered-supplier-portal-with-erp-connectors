import type { NextConfig } from "next";

// Cross-origin isolation on every page: the buyer assistant (the floating chat widget, on all pages) runs its browser
// models (served from /models) as multi-threaded WASM, which needs SharedArrayBuffer. Same-origin assets and the
// CORS API calls to the backend are unaffected; QR codes are generated as data: URLs.
const isolation = [
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Cross-Origin-Embedder-Policy", value: "require-corp" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  async headers() {
    return [{ source: "/:path*", headers: isolation }];
  },
};

export default nextConfig;
