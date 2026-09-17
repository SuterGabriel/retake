import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // `next build` traces the import graph and copies only runtime files to
  // .next/standalone (with its own server.js). The Docker runner stage ships
  // that folder without node_modules. See apps/web/Dockerfile.
  output: "standalone",
};

export default nextConfig;
