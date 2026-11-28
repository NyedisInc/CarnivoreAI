import module from "node:module";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const PKG_NAME = "@carnivore/plugin-sdk";
const SUBPATH_TESTING = "@carnivore/plugin-sdk/testing";

function resolveSdkRoot() {
  const fromEnv = (process.env.CARNIVORE_SDK_TS_DIR || "").trim();
  if (fromEnv && fs.existsSync(path.join(fromEnv, "dist", "index.js"))) {
    return fromEnv;
  }
  const here = path.dirname(fileURLToPath(import.meta.url));
  const candidates = [
    here,
    path.resolve(here, "..", "node_modules", "@carnivore", "plugin-sdk"),
    path.resolve(here, "node_modules", "@carnivore", "plugin-sdk"),
  ];
  const nodePath = (process.env.NODE_PATH || "").trim();
  if (nodePath) {
    for (const dir of nodePath.split(path.delimiter)) {
      if (dir) {
        candidates.push(path.join(dir, "@carnivore", "plugin-sdk"));
      }
    }
  }
  for (const cand of candidates) {
    if (fs.existsSync(path.join(cand, "dist", "index.js"))) {
      return cand;
    }
  }
  return "";
}

const sdkRoot = resolveSdkRoot();
if (sdkRoot && typeof module.registerHooks === "function") {
  const entryUrl = pathToFileURL(path.join(sdkRoot, "dist", "index.js")).href;
  const testingUrl = pathToFileURL(path.join(sdkRoot, "dist", "testing.js")).href;
  module.registerHooks({
    resolve(specifier, context, nextResolve) {
      if (specifier === PKG_NAME) {
        return { url: entryUrl, shortCircuit: true };
      }
      if (specifier === SUBPATH_TESTING) {
        return { url: testingUrl, shortCircuit: true };
      }
      return nextResolve(specifier, context);
    },
  });
}
