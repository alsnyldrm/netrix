import { defineConfig } from "vite";
export default defineConfig({
  server: { proxy: { "/api": { target: "http://127.0.0.1:8201", ws: true } } },
  build: { target: "es2022" },
});
