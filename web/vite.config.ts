import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: { target: "es2022" },
  // vitest reads this block; not part of vite's own types
  test: { environment: "node", include: ["src/**/*.test.ts"] },
} as never);
