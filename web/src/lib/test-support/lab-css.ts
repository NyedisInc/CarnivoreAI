import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const LAB_DIR = 'src/cplugs/devwidgetlab';

export function readLabCss(): string {
  const index = readFileSync(join(process.cwd(), LAB_DIR, 'lab.css'), 'utf8');
  const slices = [...index.matchAll(/@import '\.\/([\w.-]+\.css)';/g)].map((m) => m[1]!);
  if (slices.length === 0) throw new Error('lab.css imports no slice');
  return slices.map((name) => readFileSync(join(process.cwd(), LAB_DIR, name), 'utf8')).join('\n');
}
