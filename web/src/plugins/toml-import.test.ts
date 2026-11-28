import { describe, expect, test } from 'vitest';
import { parseToml, TomlParseError } from '../../vite.toml-parser';
import { tomlPlugin } from '../../vite.toml-plugin';
import fixtureDoc from './toml-import.fixture.toml';
import fixtureRaw from './toml-import.fixture.toml?raw';

describe('Vite/Vitest TOML support', () => {
  test('imports .toml as ESM default object via Vite plugin and preserves ?raw passthrough', () => {
    expect(fixtureDoc.schema).toBe(2);
    expect(fixtureDoc.id).toBe('sample');
    expect(fixtureDoc.default_enabled).toBe(true);
    expect(fixtureDoc.permissions).toEqual({ read: ['sessions'], write: ['notify'] });
    expect(fixtureDoc.ui).toEqual({
      routes: true,
      tabs: ['sample'],
      widgets: ['card'],
      contribute: {
        'session.row_actions': [{ id: 'pin', label: 'Pin' }],
        'terminal.toolbar': [{ id: 'snap', label: 'Snap' }],
      },
    });
    expect(fixtureDoc.mcp).toEqual({
      tools: [{ name: 'sample_ping', description: 'Ping from TOML', gate: 'read', inputSchema: { type: 'object' } }],
    });
    expect(fixtureDoc.widgets).toEqual({
      card: { instancing: 'singleton', fits: { sizes: ['small', 'medium'], anySize: false } },
    });
    expect(typeof fixtureRaw).toBe('string');
    expect(fixtureRaw).toContain('schema = 2');
  });

  test('parses TOML 1.0 strings, numbers, dates, arrays, dotted keys, and arrays of tables', () => {
    const parsed = parseToml(
      `
# header comment
title = "hello \\u0041 \\U0001F600"
raw = 'C:\\path\\stays'
multi = """
line one \\
   line two"""
multi_lit = '''
literal "quotes" 'here''''
hex = 0xdead_beef
oct = 0o755
bin = 0b1010_0101
flt = -1_000.25e+2
dt = 2026-11-25T08:30:00Z
a.b.c = 42
arr = [
  1, # inline comment
  2,
]

[[items]]
name = "one"

[[items]]
name = "two"
inline = { k = true, nested = { x = 7 } }
`,
      'unit.toml',
    );

    expect(parsed.title).toBe('hello A \u{1F600}');
    expect(parsed.raw).toBe('C:\\path\\stays');
    expect(parsed.multi).toBe('line one line two');
    expect(parsed.multi_lit).toBe('literal "quotes" \'here\'');
    expect(parsed.hex).toBe(0xdeadbeef);
    expect(parsed.oct).toBe(0o755);
    expect(parsed.bin).toBe(0b10100101);
    expect(parsed.flt).toBe(-100025);
    expect(parsed.dt).toBe('2026-11-25T08:30:00Z');
    expect(parsed.a).toEqual({ b: { c: 42 } });
    expect(parsed.arr).toEqual([1, 2]);
    expect(parsed.items).toEqual([
      { name: 'one' },
      { name: 'two', inline: { k: true, nested: { x: 7 } } },
    ]);
  });

  test('rejects duplicate keys, table redefinitions, inline-table mutations, and prevents prototype pollution', () => {
    expect(() => parseToml('a = 1\na = 2\n')).toThrow(TomlParseError);
    expect(() => parseToml('[a]\nx = 1\n[a]\ny = 2\n')).toThrow(TomlParseError);
    expect(() => parseToml('a.b = 1\n[a]\nc = 2\n')).toThrow(TomlParseError);
    expect(() => parseToml('a = { x = 1 }\n[a]\ny = 2\n')).toThrow(TomlParseError);
    expect(() => parseToml('a = [1]\n[[a]]\nx = 2\n')).toThrow(TomlParseError);
    expect(() => parseToml('a = { x = 1, }\n')).toThrow(TomlParseError);
    expect(() => parseToml('bad = "unterminated\n')).toThrow(TomlParseError);

    const protoDotted = parseToml('__proto__.polluted = true\n');
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
    expect(Object.hasOwn(protoDotted, '__proto__')).toBe(true);

    const protoTable = parseToml('["__proto__"]\nkey = "safe"\n');
    expect(({} as Record<string, unknown>).key).toBeUndefined();
    expect((protoTable['__proto__'] as Record<string, unknown>).key).toBe('safe');
  });

  test('allows TOML 1.0 sub-tables under dotted-key parents while rejecting invalid dotted-leaf reopenings', () => {
    const manifestLike = parseToml(
      'ui.routes = true\n[ui.contribute]\n"session.row_actions" = [{ id = "pin", label = "Pin" }]\n',
    );
    expect(manifestLike).toEqual({
      ui: {
        routes: true,
        contribute: {
          'session.row_actions': [{ id: 'pin', label: 'Pin' }],
        },
      },
    });

    expect(parseToml('a.b = 1\n[a.c]\nd = 2\n')).toEqual({ a: { b: 1, c: { d: 2 } } });
    expect(parseToml('a.b.c = 1\n[a.b.d]\ne = 2\n')).toEqual({ a: { b: { c: 1, d: { e: 2 } } } });
    expect(parseToml('[x.a.c]\nd = 2\n[x]\na.b = 1\n')).toEqual({ x: { a: { c: { d: 2 }, b: 1 } } });

    expect(() => parseToml('a.b.c = 1\n[a.b]\nd = 2\n')).toThrow(TomlParseError);
    expect(() => parseToml('a = { b = 1 }\n[a.c]\nd = 2\n')).toThrow(TomlParseError);
    expect(() => parseToml('[x.a.c]\nd = 2\n[x]\na.b = 1\n[x.a]\ne = 3\n')).toThrow(TomlParseError);
  });

  test('emits prototype-safe JSON.parse ESM codegen in tomlPlugin for __proto__ keys', async () => {
    const plugin = tomlPlugin();
    const transform = plugin.transform as (code: string, id: string) => { code: string; moduleType?: string } | null;

    for (const src of ['["__proto__"]\npolluted = true\n', '__proto__.polluted = true\n']) {
      const out = transform.call({}, src, '/virtual/proto.toml');
      expect(out).not.toBeNull();
      expect(out!.moduleType).toBe('js');
      expect(out!.code).toMatch(/^export default JSON\.parse\(/);

      const mod = (await import(/* @vite-ignore */ `data:text/javascript;charset=utf-8,${encodeURIComponent(out!.code)}`)) as {
        default: Record<string, unknown>;
      };
      const evaluated = mod.default;
      expect(Object.getPrototypeOf(evaluated)).toBe(Object.prototype);
      expect(Object.hasOwn(evaluated, '__proto__')).toBe(true);
      expect(evaluated.polluted).toBeUndefined();
      expect((evaluated['__proto__'] as Record<string, unknown>).polluted).toBe(true);
      expect(({} as Record<string, unknown>).polluted).toBeUndefined();
    }
  });
});
