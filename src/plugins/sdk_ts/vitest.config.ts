import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

export default {
  resolve: {
    alias: {
      "@carnivore/plugin-sdk/testing": path.join(here, "src/testing.ts"),
      "@carnivore/plugin-sdk": path.join(here, "src/index.ts"),
    },
  },
  test: {
    include: [path.join(here, "tests/**/*.test.ts")],
    environment: "node",
  },
};
