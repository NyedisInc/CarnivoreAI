
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, test } from 'vitest';

const ROOT = path.resolve(__dirname, '..', '..', '..', '..', '..');
const read = (rel: string): string => fs.readFileSync(path.join(ROOT, rel), 'utf8');

/** terminal.js's own marker line; see the comment on it in that file. */
const CLASS_END = '// THE CLASS ENDS ABOVE.';

function world(): {
  build: (options?: Record<string, unknown>) => { _xtermOptionsBase?: unknown };
  seen: unknown[];
  XTERM_OPTIONS: Readonly<Record<string, unknown>>;
} {
  const seen: unknown[] = [];
  const sandbox: Record<string, unknown> = {
    console: { log() {}, warn() {}, error() {}, debug() {} },
    document: { getElementById: () => null, querySelector: () => null },
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    Promise,
    TextEncoder,
    WebSocket: { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(read('client/js/terminal-client-factory.js'), sandbox, {
    filename: 'terminal-client-factory.js',
  });
  const src = read('client/js/terminal.js');
  const cut = src.indexOf(CLASS_END);
  expect(cut, 'terminal.js no longer carries its class-end marker').toBeGreaterThan(0);
  vm.runInContext(src.slice(0, cut) + '\nwindow.CloudeTerminal.register(Terminal);', sandbox, {
    filename: 'terminal.js',
  });

  const factory = sandbox.CloudeTerminal as {
    createTerminalClient: (el: unknown, o?: Record<string, unknown>) => { _xtermOptionsBase?: unknown };
    XTERM_OPTIONS: Readonly<Record<string, unknown>>;
  };
  return {
    build: (options = {}) => factory.createTerminalClient(null, options),
    seen,
    XTERM_OPTIONS: factory.XTERM_OPTIONS,
  };
}

describe('the xterm options every terminal is built from', () => {
  test('the primary and a cell hold the SAME object, not two equal ones', () => {
    const w = world();
    const primary = w.build();
    const cell = w.build({ chrome: {}, wiring: {}, inputOwner: 'terminal:ses_7' });

    expect(primary._xtermOptionsBase).toBe(cell._xtermOptionsBase);
    expect(primary._xtermOptionsBase).toBe(w.XTERM_OPTIONS);
  });

  test('the shared object is frozen, so configuring one cannot reconfigure all', () => {
    const w = world();
    expect(Object.isFrozen(w.XTERM_OPTIONS)).toBe(true);
  });

  test('it carries the settings a cell must not be allowed to differ on', () => {
    const w = world();
    const o = w.XTERM_OPTIONS as Record<string, unknown>;
    expect(Object.keys(o).length).toBeGreaterThanOrEqual(11);
    expect(o.fontSize).toBe(14);
    expect(typeof o.fontFamily).toBe('string');
    expect(o.scrollback).toBe(5000);
    expect(o.scrollOnUserInput).toBe(false);
    expect(o.allowProposedApi).toBe(true);
    expect(o.convertEol).toBe(false);
    expect('theme' in o).toBe(false);
  });

  test('a client built outside the factory is refused rather than given a literal', () => {
    const w = world();
    const client = w.build() as unknown as { initTerminal: () => void; _xtermOptionsBase: unknown };
    (client as unknown as Record<string, unknown>)._xtermOptionsBase = null;
    expect(() => client.initTerminal()).toThrow(/xterm options/);
  });
});
