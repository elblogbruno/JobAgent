// Bundles the extension into dist/. esbuild is the only build dependency:
// content scripts cannot use ES module imports, so a bundler is required.
import { build, context } from "esbuild";
import { cp, mkdir, readdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const outdir = join(root, "dist");
const watch = process.argv.includes("--watch");

const entryPoints = {
  background: "src/background/service-worker.ts",
  content: "src/content/content-script.ts",
  "dashboard-bridge": "src/content/dashboard-bridge.ts",
  popup: "src/popup/popup.ts",
  sidepanel: "src/sidepanel/sidepanel.ts",
  options: "src/options/options.ts",
};

const staticFiles = [
  "manifest.json",
  "src/popup/popup.html",
  "src/sidepanel/sidepanel.html",
  "src/options/options.html",
  "src/shared/panel.css",
  "src/content/content.css",
  "icon-16.png",
  "icon-48.png",
  "icon-128.png",
];

async function copyStatic() {
  await mkdir(outdir, { recursive: true });
  for (const file of staticFiles) {
    await cp(join(root, file), join(outdir, file.split("/").pop()));
  }
}

const options = {
  entryPoints: Object.fromEntries(
    Object.entries(entryPoints).map(([name, file]) => [name, join(root, file)]),
  ),
  outdir,
  bundle: true,
  format: "esm",
  target: "chrome114",
  platform: "browser",
  sourcemap: watch ? "inline" : false,
  minify: !watch,
  logLevel: "info",
};

await rm(outdir, { recursive: true, force: true });
await copyStatic();

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
  console.log("watching for changes; reload the unpacked extension after each build");
} else {
  await build(options);
  const files = await readdir(outdir);
  console.log(`built ${files.length} files into dist/`);
}
