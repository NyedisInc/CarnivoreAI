import type { Plugin } from 'vite';
import { parseToml } from './vite.toml-parser';

const SKIP_QUERY_RE = /[?&](?:raw|url|inline|no-inline|worker|sharedworker)\b/;

function assertFiniteJson(value: unknown, path: string): void {
  if (typeof value === 'number' && !Number.isFinite(value)) {
    throw new Error(`${path}: non-finite number (${value}) cannot be serialized as JSON`);
  }
  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i += 1) assertFiniteJson(value[i], `${path}[${i}]`);
  } else if (value !== null && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) assertFiniteJson(v, `${path}.${k}`);
  }
}

export function tomlPlugin(): Plugin {
  return {
    name: 'carnivore-toml',
    enforce: 'pre',
    transform(code, id) {
      const [filePath = '', query = ''] = id.split('?', 2);
      if (!filePath.endsWith('.toml')) return null;
      if (query && SKIP_QUERY_RE.test(`?${query}`)) return null;
      const parsed = parseToml(code, filePath);
      assertFiniteJson(parsed, filePath);
      return {
        code: `export default JSON.parse(${JSON.stringify(JSON.stringify(parsed))});\n`,
        map: null,
        moduleType: 'js',
      };
    },
  };
}
