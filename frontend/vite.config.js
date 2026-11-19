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
      transformIndexHtml: {
        // Run before Vite's HTML handler so it bundles this module instead of
        // leaving a relative app.js URL that does not exist in the output.
        order: "pre",
        handler(html) {
          return html.replace(
            '<script src="/static/app.js"></script>',
            '<script type="module" src="./app.js"></script>',
          );
        },
      },
    },
  ],
  build: {
    outDir: path.resolve(frontendDir, "dist"),
    emptyOutDir: true,
  },
});
