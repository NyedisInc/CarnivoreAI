import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build, type Rolldown } from 'vite';
import { describe, expect, it } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const CONFIG = join(HERE, '../../vite.bundle.config.ts');
const EVAL_SHAPED = /(?<![.\w$])eval\s*\(|new\s+Function\s*\(/;
const FORBIDDEN = /\/api\/v1|authFetch|\/login|localStorage|XMLHttpRequest|WebSocket|EventSource|sendBeacon/g;
const VISITOR_KEY_FILE = 'visitor-id.ts';

function code(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
}

function forbidden(text: string, stripComments = true): string[] {
  return (stripComments ? code(text) : text).match(FORBIDDEN) ?? [];
}

function addresses(text: string, stripComments = true): string[] {
  return [...new Set([...(stripComments ? code(text) : text).matchAll(/['"`](\/api\/[^'"`]*)['"`]/g)].map((m) => m[1] ?? ''))];
}

function imports(text: string): string[] {
  return [...code(text).matchAll(/(?:from\s+|import\s+)['"]([^'"]+)['"]/g)].map((m) => m[1] ?? '');
}

const ADDRESSES = ['/api/board', '/api/comments', '/api/draft', '/api/next'];

const SOURCES = readdirSync(HERE).filter((f) => /\.(ts|svelte)$/.test(f) && !f.endsWith('.test.ts'));

describe('the source of the visitor page', () => {
  it('names no owner route, no app fetch helper, no login and no token store', () => {
    expect(SOURCES).toContain('main.ts');
    for (const file of SOURCES) {
      const found = forbidden(readFileSync(join(HERE, file), 'utf8'));
      expect(found, file).toEqual(file === VISITOR_KEY_FILE ? found.filter((f) => f === 'localStorage') : []);
    }
  });

  it('keeps only the visitor key in localStorage, under its own prefix, never the secret', () => {
    const text = code(readFileSync(join(HERE, VISITOR_KEY_FILE), 'utf8'));
    expect(text).toContain("'carnivore.publicboard.visitor.'");
    expect(text).not.toMatch(/setItem\([^)]*secret/);
  });

  it('imports only itself, svelte, the plugin catalog, the stylesheet and the one popup frame', () => {
    const allowed = /^(\.\/[\w.-]+|svelte|\.\.\/\.\.\/catalog\.en\.js|\.\.\/\.\.\/\.\.\/sdk\/anchored-popup)$/;
    for (const file of SOURCES) {
      for (const spec of imports(readFileSync(join(HERE, file), 'utf8'))) {
        expect(spec, `${file} imports ${spec}`).toMatch(allowed);
      }
    }
  });

  it('asks for exactly the public table\'s addresses', () => {
    expect([...new Set(SOURCES.flatMap((f) => addresses(readFileSync(join(HERE, f), 'utf8'))))].sort()).toEqual(ADDRESSES);
  });

  it('the checks go red on a planted owner route, helper, storage or socket (negative control)', () => {
    expect(forbidden("fetch('/api/v1/cplugs/reviewboard/public/links')")).toEqual(['/api/v1']);
    expect(forbidden("import { authFetch } from '../../lib/auth'")).toEqual(['authFetch']);
    expect(forbidden("localStorage.setItem('k', secret)")).toEqual(['localStorage']);
    expect(forbidden("new WebSocket('/ws')")).toEqual(['WebSocket']);
    expect(forbidden('/* authFetch */ // localStorage')).toEqual([]);
    expect(addresses("fetch('/api/v1/x'); fetch(`/api/board`)")).toEqual(['/api/v1/x', '/api/board']);
    expect(imports("import a from '../../lib/auth'; export * from './x'")).toEqual(['../../lib/auth', './x']);
  });
});

describe('the shipped artifact', () => {
  async function emitted(): Promise<{ js: string; css: string; names: string[] }> {
    const result = (await build({ configFile: CONFIG, logLevel: 'silent', build: { write: false } })) as Rolldown.RolldownOutput | Rolldown.RolldownOutput[];
    const files = (Array.isArray(result) ? result : [result]).flatMap((r) => r.output);
    const text = (name: string): string => {
      const file = files.find((f) => f.fileName === name);
      if (!file) throw new Error(`the build emitted no ${name}; got ${files.map((f) => f.fileName).join(', ')}`);
      return String('code' in file ? file.code : file.source);
    };
    return { js: text('reviewboard-public.js'), css: text('reviewboard-public.css'), names: files.map((f) => f.fileName) };
  }

  it('is one script and one style sheet that reach no owner route and hold no token store', async () => {
    const { js, css } = await emitted();
    expect(forbidden(js, false).filter((f) => f !== 'localStorage')).toEqual([]);
    expect(js.match(/localStorage/g)?.length ?? 0).toBeLessThanOrEqual(2);
    expect(js).toContain('/api/board');
    expect(js).toContain('sessionStorage');
    expect(js).not.toMatch(/\bimport\(/);
    expect(js).not.toMatch(EVAL_SHAPED);
    expect(css.match(/url\(\s*(?!['"]?data:)[^)]*\)/g) ?? []).toEqual([]);
  });

  it('ships none of the review board\'s owner strings to a person who only holds a link', async () => {
    const { js } = await emitted();
    expect(js).not.toContain('cplug.reviewboard.relink.title');
    expect(js).not.toContain('link this board to a task');
    expect(js).toContain('cplug.reviewboard.public.page.revision');
  });

  it('emits exactly one script and one style sheet, named as the route table serves them', async () => {
    const { names } = await emitted();
    expect([...names].sort()).toEqual(['reviewboard-public.css', 'reviewboard-public.js']);
  });

  it('the artifact checks go red on a planted eval, remote url or owner route (negative control)', () => {
    expect('x = eval(y)').toMatch(EVAL_SHAPED);
    expect('x = new Function("a")').toMatch(EVAL_SHAPED);
    expect('obj.eval(y)').not.toMatch(EVAL_SHAPED);
    expect('a{background:url(https://evil.example/x.png)}'.match(/url\(\s*(?!['"]?data:)[^)]*\)/g)).toHaveLength(1);
    expect('a{background:url("data:image/png;base64,AA")}'.match(/url\(\s*(?!['"]?data:)[^)]*\)/g)).toBeNull();
    expect('a{background:url(/x.png)}'.match(/url\(\s*(?!['"]?data:)[^)]*\)/g)).toHaveLength(1);
  });

  it('asks for exactly the public table\'s addresses', async () => {
    const { js } = await emitted();
    expect(addresses(js, false).sort()).toEqual(ADDRESSES);
  });
});
