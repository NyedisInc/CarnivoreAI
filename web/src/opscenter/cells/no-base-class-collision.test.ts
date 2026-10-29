import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, test } from 'vitest';

const SRC = join(__dirname, '..', '..');
const CELLS = __dirname;
const BASE = join(SRC, 'lib', 'base');

function filesUnder(dir: string, ext: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? filesUnder(path, ext) : path.endsWith(ext) ? [path] : [];
  });
}

function classesIn(css: string): Set<string> {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\{[^{}]*\}/g, '{}');
  return new Set([...stripped.matchAll(/\.(-?[a-zA-Z_][\w-]*)/g)].map((m) => m[1] ?? ''));
}

function scopedClassesOf(source: string): Set<string> {
  const block = /<style[^>]*>([\s\S]*?)<\/style>/.exec(source)?.[1] ?? '';
  return classesIn(block.replace(/:global\([^)]*\)/g, ''));
}

describe('a cell never reuses a base part class name', () => {
  const baseClasses = new Set(filesUnder(BASE, '.css').flatMap((file) => [...classesIn(readFileSync(file, 'utf8'))]));

  test('the base set is not empty (the check can go red)', () => {
    expect(baseClasses.has('oc-task')).toBe(true);
  });

  test('no cell style defines a base class', () => {
    const clashes: string[] = [];
    for (const file of filesUnder(CELLS, '.svelte')) {
      for (const name of scopedClassesOf(readFileSync(file, 'utf8'))) {
        if (baseClasses.has(name)) clashes.push(`${file.slice(CELLS.length + 1)}: .${name}`);
      }
    }
    expect(clashes).toEqual([]);
  });
});
