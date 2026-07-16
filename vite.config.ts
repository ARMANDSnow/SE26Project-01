import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src")
    }
  },
  server: {
    port: 5173,
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${process.env.E2E_BACKEND_PORT ?? "8000"}`,
        changeOrigin: true
      }
    }
  }
});
