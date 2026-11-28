/* the Task Manager */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from 'vitest';

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const CELL_HOST = join(WEB, 'src/opscenter/CellHost.svelte');
const CELL_BOOT = join(WEB, 'src/plugins/host/cell-boot.ts');
const KNOWN_CELL_ENTRIES = ['src/main.ts', 'src/popout/main.ts', 'src/widget-harness/main.ts', 'src/widget-preview/main.ts'];
const SUFFIXES = ['', '.ts', '.js', '.svelte', '/index.ts', '/index.js'];
const IMPORT = /(?:import|export)(\s[^'"]*?)from\s*['"]([^'"]+)['"]|import\s*['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)/g;
const GLOB = /import\.meta\.glob\(\s*['"](\.[^'"*]*)\*([^'"*]*)['"]/g;

function typeOnly(clause: string): boolean {
  const text = clause.trim();
  if (/^type[\s{]/.test(text)) return true;
  const names = /^\{([^}]*)\}$/.exec(text)?.[1]?.split(',').map((n) => n.trim()).filter(Boolean);
  return !!names && names.length > 0 && names.every((n) => /^type\s/.test(n));
}

function viteConfigs(): string[] {
  const top = readdirSync(WEB).filter((name) => /^vite(\..+)?\.config\.ts$/.test(name)).map((name) => join(WEB, name));
  const plugins = join(WEB, 'src/plugins');
  const own = readdirSync(plugins).map((name) => join(plugins, name, 'vite.bundle.config.ts')).filter((path) => existsSync(path));
  return [...top, ...own];
}

function entriesOf(config: string): string[] {
  const text = readFileSync(config, 'utf8');
  const out: string[] = [];
  for (const [, spec] of text.matchAll(/new URL\(\s*['"]([^'"]+)['"]\s*,\s*import\.meta\.url\s*\)/g)) {
    const target = resolve(dirname(config), spec!);
    if (target.endsWith('.ts') && existsSync(target)) out.push(target);
    const page = join(target, 'index.html');
    if (!target.endsWith('.ts') && existsSync(page)) {
      for (const [, src] of readFileSync(page, 'utf8').matchAll(/<script[^>]*type="module"[^>]*src="(\.[^"]+)"/g)) out.push(resolve(target, src!));
    }
  }
  return out;
}

function resolveImport(from: string, spec: string): string | null {
  if (!spec.startsWith('.')) return null;
  const base = resolve(dirname(from), spec);
  for (const suffix of SUFFIXES) {
    const path = base + suffix;
    if (existsSync(path) && statSync(path).isFile()) return path;
  }
  return null;
}

function globFiles(from: string, head: string, tail: string): string[] {
  const folder = resolve(dirname(from), head.endsWith('/') ? head : dirname(head));
  if (!existsSync(folder)) return [];
  return readdirSync(folder).map((name) => join(folder, name + tail)).filter((path) => existsSync(path) && statSync(path).isFile());
}

function reach(entry: string): Set<string> {
  const seen = new Set([entry]);
  const queue = [entry];
  while (queue.length) {
    const file = queue.shift()!;
    if (file === CELL_BOOT) continue;
    if (!/\.(ts|js|svelte)$/.test(file)) continue;
    const text = readFileSync(file, 'utf8');
    const found: string[] = [];
    for (const match of text.matchAll(IMPORT)) {
      if (match[1] !== undefined && typeOnly(match[1])) continue;
      const hit = resolveImport(file, match[2] ?? match[3] ?? match[4]!);
      if (hit) found.push(hit);
    }
    for (const [, head, tail] of text.matchAll(GLOB)) found.push(...globFiles(file, head!, tail!));
    for (const hit of found) {
      if (seen.has(hit)) continue;
      seen.add(hit);
      queue.push(hit);
    }
  }
  return seen;
}

function bootsCells(entry: string): boolean {
  const text = readFileSync(entry, 'utf8');
  const imported = [...text.matchAll(/import\s*\{([^}]*)\}\s*from\s*['"]([^'"]+)['"]/g)].some(
    ([, names, spec]) => /\bbootPluginCells\b/.test(names!) && resolveImport(entry, spec!) === CELL_BOOT,
  );
  return imported && /^bootPluginCells\(\);/m.test(text);
}

test('every bundle entry that reaches the cell host imports and calls bootPluginCells', () => {
  const configs = viteConfigs();
  expect(configs.length).toBeGreaterThan(5);
  const drawing: string[] = [];
  for (const config of configs) {
    const entries = entriesOf(config);
    expect(entries, `${relative(WEB, config)}: no entry this test can read`).not.toEqual([]);
    for (const entry of entries) if (reach(entry).has(CELL_HOST)) drawing.push(relative(WEB, entry));
  }
  const unique = [...new Set(drawing)].sort();
  expect(unique).toEqual(expect.arrayContaining(KNOWN_CELL_ENTRIES));
  expect(unique.filter((entry) => !bootsCells(join(WEB, entry))), 'entries that reach CellHost without bootPluginCells()').toEqual([]);
});
