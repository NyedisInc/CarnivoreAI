/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { installScreenFlags, raiseFlag, setFlag } from './page-flags';

beforeEach(() => {
  document.body.className = '';
  document.documentElement.className = '';
  document.body.innerHTML = '<div id="terminal-screen" class="screen"><div id="terminal-grid"></div></div>';
});

afterEach(() => {
  document.body.innerHTML = '';
});

describe('setFlag', () => {
  it('toggles the class on the flag anchor and is idempotent', () => {
    setFlag('drawer-open', true);
    setFlag('drawer-open', true);
    expect(document.body.classList.contains('ps-drawer-open')).toBe(true);
    setFlag('drawer-open', false);
    expect(document.body.classList.contains('ps-drawer-open')).toBe(false);
  });

  it('writes every anchor a flag names', () => {
    setFlag('grid-surface', true);
    expect(document.body.classList.contains('ps-grid-surface')).toBe(true);
    expect(document.getElementById('terminal-grid')!.classList.contains('ps-grid-surface')).toBe(true);
  });
});

describe('raiseFlag', () => {
  it('keeps the class while any claim is open, so a replacement mounting first never flickers it off', () => {
    const first = raiseFlag('phone-tabs');
    const second = raiseFlag('phone-tabs');
    first();
    expect(document.body.classList.contains('ps-phone-tabs')).toBe(true);
    second();
    expect(document.body.classList.contains('ps-phone-tabs')).toBe(false);
  });

  it('ignores a second release of the same claim', () => {
    const a = raiseFlag('topbar');
    const b = raiseFlag('topbar');
    a();
    a();
    expect(document.documentElement.classList.contains('ps-topbar')).toBe(true);
    b();
    expect(document.documentElement.classList.contains('ps-topbar')).toBe(false);
  });
});

describe('one writer per flag', () => {
  it('throws when a claimed flag is also set, and when a set flag is also claimed', () => {
    const release = raiseFlag('browser-screen');
    expect(() => setFlag('browser-screen', false)).toThrow(/one/);
    release();
    setFlag('page-back', true);
    expect(() => raiseFlag('page-back')).toThrow(/one/);
  });
});

describe('installScreenFlags', () => {
  it('mirrors #terminal-screen.active and .terminal-screen--empty, following later class writes', async () => {
    const screen = document.getElementById('terminal-screen')!;
    const stop = installScreenFlags();
    expect(document.body.classList.contains('ps-terminal-active')).toBe(false);
    screen.classList.add('active');
    await Promise.resolve();
    expect(document.body.classList.contains('ps-terminal-active')).toBe(true);
    expect(document.body.classList.contains('ps-terminal-empty-active')).toBe(false);
    screen.classList.add('terminal-screen--empty');
    await Promise.resolve();
    expect(document.body.classList.contains('ps-terminal-empty-active')).toBe(true);
    screen.classList.remove('active');
    await Promise.resolve();
    expect(document.body.classList.contains('ps-terminal-active')).toBe(false);
    expect(document.body.classList.contains('ps-terminal-empty-active')).toBe(false);
    stop?.();
  });

  it('does nothing when the screen is not in the document', () => {
    document.body.innerHTML = '';
    expect(installScreenFlags()).toBeNull();
  });

  it('does not observe the subtree: an insert elsewhere raises no callback work', async () => {
    const screen = document.getElementById('terminal-screen')!;
    const stop = installScreenFlags();
    screen.classList.add('active');
    await Promise.resolve();
    document.body.classList.remove('ps-terminal-active');
    screen.appendChild(document.createElement('div'));
    await Promise.resolve();
    expect(document.body.classList.contains('ps-terminal-active')).toBe(false);
    stop?.();
  });
});
