import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

export function buildConfigs(pkg) {
  const configs = [];
  for (const step of pkg.scripts.build.split("&&")) {
    const m = step.match(/--config\s+(\S+)/);
    if (/\bvite\s+build\b/.test(step)) configs.push(m ? m[1] : "vite.config.ts");
  }
  return configs;
}

export function pkgDirOf(id) {
  const clean = id.split("?")[0].replace(/^\0/, "");
  const at = clean.lastIndexOf("/node_modules/");
  if (at < 0) return null;
  const rest = clean.slice(at + "/node_modules/".length).split("/");
  const len = rest[0].startsWith("@") ? 2 : 1;
  return clean.slice(0, at + "/node_modules/".length) + rest.slice(0, len).join("/");
}

export async function bundledPackages(webDir) {
  process.chdir(webDir);
  const require = createRequire(path.join(webDir, "package.json"));
  const { build } = await import(require.resolve("vite"));
  const pkg = JSON.parse(fs.readFileSync(path.join(webDir, "package.json"), "utf8"));
  const dirs = new Set();
  for (const cfg of buildConfigs(pkg)) {
    const result = await build({ configFile: path.join(webDir, cfg), logLevel: "silent", build: { write: false } }).catch((e) => {
      throw new Error(`vite build ${cfg} failed: ${e.message}`);
    });
    for (const out of [].concat(result)) {
      for (const o of out.output ?? []) {
        for (const id of Object.keys(o.modules ?? {})) {
          const d = pkgDirOf(id);
          if (d) dirs.add(d);
        }
      }
    }
  }
  const packages = [...dirs].map((dir) => {
    const meta = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
    return { name: meta.name, version: meta.version, dir };
  });
  packages.sort((a, b) => (a.name + a.version).localeCompare(b.name + b.version));
  return packages;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const webDir = path.resolve(process.argv[2] ?? "web");
  process.stdout.write(JSON.stringify({ packages: await bundledPackages(webDir) }, null, 1) + "\n");
}
