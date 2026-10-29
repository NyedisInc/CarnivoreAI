import fs from 'node:fs';
import { join } from 'node:path';
import { expect } from 'vitest';

const FILE = join(process.cwd(), 'src/lib/zone-shell/__goldens__/dom.json');

export function normalized(el: Element): string {
  return el.outerHTML
    .replace(/\s?svelte-[a-z0-9]+/g, '')
    .replace(/\sclass=""/g, '')
    .replace(/<!---->/g, '');
}

function readAll(): Record<string, string> {
  try {
    return JSON.parse(fs.readFileSync(FILE, 'utf8')) as Record<string, string>;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return {};
    throw error;
  }
}

export function matchGolden(name: string, el: Element | null): void {
  expect(el, `golden ${name}: nothing to compare`).not.toBeNull();
  const html = normalized(el!);
  if (process.env['UPDATE_GOLDENS'] === '1') {
    const all = readAll();
    all[name] = html;
    fs.writeFileSync(FILE, `${JSON.stringify(all, Object.keys(all).sort(), 2)}\n`);
    return;
  }
  const want = readAll()[name];
  expect(want, `golden ${name} was never recorded`).toBeDefined();
  expect(html).toBe(want);
}
