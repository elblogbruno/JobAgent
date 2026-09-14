// Bundles the tests, then hands them to Node's own test runner. No test
// framework needed: the code under test is plain functions over strings.
import { build } from "esbuild";
import { readdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = dirname(fileURLToPath(import.meta.url));
const outdir = join(root, ".test-build");

const tests = (await readdir(join(root, "tests"))).filter((file) => file.endsWith(".test.ts"));
if (!tests.length) {
  console.log("no tests found");
  process.exit(0);
}

await rm(outdir, { recursive: true, force: true });
await build({
  entryPoints: tests.map((file) => join(root, "tests", file)),
  outdir,
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node20",
  external: ["node:*"],
  logLevel: "warning",
});

const result = spawnSync(
  process.execPath,
  ["--test", ...tests.map((file) => join(outdir, file.replace(/\.ts$/, ".js")))],
  { stdio: "inherit" },
);
await rm(outdir, { recursive: true, force: true });
process.exit(result.status ?? 1);
