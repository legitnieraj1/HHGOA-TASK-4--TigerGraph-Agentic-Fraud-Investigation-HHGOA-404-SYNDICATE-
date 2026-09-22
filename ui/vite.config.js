import { defineConfig } from "vite";

// Static build only (no dev server proxy needed -- FastAPI serves ui/dist directly, spec's own
// pattern of "backend serves the frontend" per api/main.py's StaticFiles mount).
export default defineConfig({
  base: "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
