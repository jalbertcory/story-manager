import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./tests/setup.js",
    include: ["src/**/*.{test,spec}.?(c|m)[jt]s?(x)"],
    exclude: ["./tests-e2e/**"],
  },
});
