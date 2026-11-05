import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { knownListRatchet, stripComments, walkSources } from './source-scan';

describe('source-scan', () => {
  it('strips comments but keeps a URL', () => {
    expect(stripComments("a(); // note\n/* b() */ c('http://x');")).toBe("a(); \n c('http://x');");
  });

  it('knownListRatchet names a new offender and a stale row', () => {
    expect(knownListRatchet(['a', 'b'], ['a', 'c'])).toEqual({ unlisted: ['b'], stale: ['c'] });
    expect(knownListRatchet(['a'], ['a'])).toEqual({ unlisted: [], stale: [] });
  });

  it('walkSources finds this folder\'s files and honors skipDirs and exclude', () => {
    expect(walkSources(__dirname, /\.ts$/)).toEqual(['source-scan.test.ts', 'source-scan.ts']);
    expect(walkSources(__dirname, /\.ts$/, { exclude: /\.test\./ })).toEqual(['source-scan.ts']);
    expect(walkSources(path.dirname(__dirname), /^source-scan\.ts$/, { skipDirs: /^test-support$/ })).toEqual([]);
  });
});
