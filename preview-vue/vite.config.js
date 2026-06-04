import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/places": {
        target: process.env.VITE_NEXT_STOPS_API_BASE || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/districts": {
        target: process.env.VITE_NEXT_STOPS_API_BASE || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/health": {
        target: process.env.VITE_NEXT_STOPS_API_BASE || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/build": {
        target: process.env.VITE_NEXT_STOPS_API_BASE || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
