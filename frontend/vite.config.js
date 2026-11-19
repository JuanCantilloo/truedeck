import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const staticDir = path.resolve(frontendDir, "../backend/static");

export default defineConfig({
  // The app's HTML and JavaScript currently live in backend/static.
  root: staticDir,
  plugins: [
    {
      name: "truedeck-static-entry",
      transformIndexHtml(html) {
        // Keep FastAPI's /static/app.js path intact at runtime, while letting
        // Vite bundle the same script for the static Vercel build.
        return html.replace(
          '<script src="/static/app.js"></script>',
          '<script type="module" src="./app.js"></script>',
        );
      },
    },
  ],
  build: {
    outDir: path.resolve(frontendDir, "dist"),
    emptyOutDir: true,
  },
});
