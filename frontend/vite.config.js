import process from "node:process";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const parseAllowedHosts = (value) => {
  if (!value) {
    return undefined;
  }

  const hosts = value
    .split(",")
    .map((host) => host.trim())
    .filter(Boolean);

  return hosts.length > 0 ? hosts : undefined;
};

const allowedHosts = parseAllowedHosts(process.env.VITE_ALLOWED_HOSTS);

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts,
    port: 5173,
    strictPort: true,
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
