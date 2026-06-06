import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const apiTarget = process.env.VITE_NEXT_STOPS_API_BASE || "http://127.0.0.1:8790";
const attractionTarget = process.env.VITE_ATTRACTION_API_BASE || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 5174,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
      "/places": {
        target: attractionTarget,
        changeOrigin: true,
      },
      "/districts": {
        target: attractionTarget,
        changeOrigin: true,
      },
      "/health": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});
