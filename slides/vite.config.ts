import react from "@vitejs/plugin-react";
import path from "path";
import { defineConfig } from "vite";

// GitHub Pages project site: https://<user>.github.io/<repo>/
const repo = process.env.GITHUB_REPOSITORY?.split("/")[1];
const base =
  process.env.VITE_BASE?.replace(/\/?$/, "/") ||
  (repo ? `/${repo}/` : "/");

export default defineConfig({
  plugins: [react()],
  base,
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
});
