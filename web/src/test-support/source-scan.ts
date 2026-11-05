import fs from 'node:fs';
import path from 'node:path';

export function walkSources(dir: string, ext: RegExp, options: { skipDirs?: RegExp; exclude?: RegExp; base?: string } = {}): string[] {
  const base = options.base ?? dir;
  const walk = (current: string): string[] =>
    fs.readdirSync(current, { withFileTypes: true }).flatMap((entry) => {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) return options.skipDirs?.test(entry.name) ? [] : walk(full);
      return ext.test(entry.name) && !options.exclude?.test(entry.name) ? [path.relative(base, full)] : [];
    });
  return walk(dir).sort();
}

export function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
}

export function knownListRatchet(found: readonly string[], known: readonly string[]): { unlisted: string[]; stale: string[] } {
  return { unlisted: found.filter((one) => !known.includes(one)), stale: known.filter((one) => !found.includes(one)) };
}
