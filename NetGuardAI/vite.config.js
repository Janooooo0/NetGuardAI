import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiPort = Number(process.env.PORT || process.env.VITE_API_PORT || 8000);
const webHost = process.env.VITE_HOST || "127.0.0.1";

export default defineConfig({
  plugins: [react()],
  server: {
    host: webHost,
    proxy: {
      "/api": `http://127.0.0.1:${apiPort}`,
    },
  },
});
