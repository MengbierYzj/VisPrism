import { execFileSync } from "node:child_process";
import { mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import * as vega from "../frontend/node_modules/vega/build/vega-node.js";
import * as vegaLite from "../frontend/node_modules/vega-lite/build/vega-lite.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const datasetDir = path.join(root, "data", "dataset");
const outputDir = path.join(root, "data", "vega_lite_png");
const tempDir = path.join(outputDir, ".rendering");
const edgePath = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";

async function findJsonFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const entryPath = path.join(dir, entry.name);
    return entry.isDirectory()
      ? findJsonFiles(entryPath)
      : entry.isFile() && entry.name.endsWith(".json") ? [entryPath] : [];
  }));
  return nested.flat();
}

await mkdir(outputDir, { recursive: true });
await rm(tempDir, { recursive: true, force: true });
await mkdir(tempDir);

const jsonFiles = await findJsonFiles(datasetDir);
const failures = [];

for (const jsonPath of jsonFiles) {
  const relative = path.relative(datasetDir, jsonPath);
  const outputName = `${path.basename(path.dirname(jsonPath))}.png`;
  const svgPath = path.join(tempDir, `${outputName}.svg`);
  const pngPath = path.join(outputDir, outputName);

  try {
    const spec = JSON.parse(await readFile(jsonPath, "utf8"));
    const compiled = vegaLite.compile(spec).spec;
    const view = new vega.View(vega.parse(compiled), { renderer: "none" }).initialize();
    const svg = await view.toSVG();
    await writeFile(svgPath, svg, "utf8");
    const bounds = /<svg[^>]*\bwidth="([0-9.]+)"[^>]*\bheight="([0-9.]+)"/.exec(svg);
    const width = Math.ceil(Number(bounds?.[1]) || 1200);
    const height = Math.ceil(Number(bounds?.[2]) || 800);
    execFileSync(edgePath, [
      "--headless", "--disable-gpu", "--hide-scrollbars", "--force-color-profile=srgb",
      `--window-size=${width},${height}`, `--screenshot=${pngPath}`,
      pathToFileURL(svgPath).href,
    ], { stdio: "pipe" });
    if ((await stat(pngPath)).size === 0) throw new Error("PNG file is empty");
    console.log(`OK  ${relative} -> ${path.relative(root, pngPath)}`);
  } catch (error) {
    failures.push(`${relative}: ${error.message}`);
    console.error(`FAIL ${relative}: ${error.message}`);
  }
}

await rm(tempDir, { recursive: true, force: true });
if (failures.length) {
  throw new Error(`Failed to render ${failures.length} file(s):\n${failures.join("\n")}`);
}
console.log(`Rendered ${jsonFiles.length} PNG files to ${path.relative(root, outputDir)}`);
