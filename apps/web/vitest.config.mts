import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname) } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./test/setup.ts"],
    include: ["app/**/*.test.{ts,tsx}", "features/**/*.test.{ts,tsx}", "lib/**/*.test.{ts,tsx}"],
  },
});
