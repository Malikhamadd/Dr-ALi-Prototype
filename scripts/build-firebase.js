import { build } from "esbuild";
import { mkdir, copyFile } from "node:fs/promises";
import { resolve } from "node:path";

const outDir = resolve("mirror/videa-saversion.webflow.io/assets");
const outFile = resolve(outDir, "firebase-init.js");

await mkdir(outDir, { recursive: true });

await build({
  entryPoints: [resolve("src/firebase-init.js")],
  outfile: outFile,
  bundle: true,
  format: "esm",
  platform: "browser",
  sourcemap: false,
  minify: true,
  target: ["es2020"],
});

// Optional: copy to root-level index.html folder if needed later.
// await copyFile(outFile, resolve("mirror/videa-saversion.webflow.io/firebase-init.js"));

console.log("Built", outFile);
