import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: process.env.BIND_IP ?? "127.2.0.1",
    port: 8020,
    proxy: {
      "/api": {
        target: "http://api:8010",
        changeOrigin: true,
      },
    },
  },
});
