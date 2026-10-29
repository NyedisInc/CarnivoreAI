/** @vitest-environment jsdom */
import { expect, test } from 'vitest';
import { bindTerminalTheme } from './theme';

test('two cells retain distinct palettes across page changes and release their scopes', () => {
  const listeners = new Set<() => void>();
  const a = { id: 'a', cssVars: { '--color-accent': 'red' }, xterm: { background: 'red' } };
  const b = { id: 'b', cssVars: { '--color-accent': 'blue' }, xterm: { background: 'blue' } };
  const fallback = { id: 'page', xterm: { background: 'black' } };
  const host = {
    Themes: {
      getSessionManifest: (context: { pinnedTheme: string | null }) => context.pinnedTheme === 'a' ? a : b,
      getActiveTerminalManifest: () => fallback,
      onXtermThemeChange: (callback: () => void) => { listeners.add(callback); return () => { listeners.delete(callback); }; },
    },
    ThemeVarWriter: {
      applyVarDiff: (style: CSSStyleDeclaration, previous: Record<string, string>, next: Record<string, string>) => {
        Object.keys(previous).forEach(key => { if (!(key in next)) style.removeProperty(key); });
        Object.entries(next).forEach(([key, value]) => style.setProperty(key, value));
        return { values: next };
      },
    },
  };
  const frameA = document.createElement('div'); frameA.className = 'oc-frame';
  const frameB = document.createElement('div'); frameB.className = 'oc-frame';
  const clientA = { term: { options: { theme: fallback.xterm } } };
  const clientB = { term: { options: { theme: fallback.xterm } } };
  const releaseA = bindTerminalTheme(clientA, frameA, { pinnedTheme: 'a' }, host);
  const releaseB = bindTerminalTheme(clientB, frameB, { pinnedTheme: 'b' }, host);
  listeners.forEach(listener => listener());
  expect(clientA.term.options.theme).toBe(a.xterm);
  expect(clientB.term.options.theme).toBe(b.xterm);
  expect(frameA.style.getPropertyValue('--color-accent')).toBe('red');
  expect(frameB.style.getPropertyValue('--color-accent')).toBe('blue');
  releaseA();
  expect(frameA.dataset.sessionTheme).toBeUndefined();
  expect(frameA.style.getPropertyValue('--color-accent')).toBe('');
  expect(clientA.term.options.theme).toBe(fallback.xterm);
  expect(clientB.term.options.theme).toBe(b.xterm);
  releaseB();
  expect(listeners.size).toBe(0);
});

test('an unpinned cell paints the page theme while a sibling keeps its pin', () => {
  const listeners = new Set<() => void>();
  const pinned = { id: 'pin', cssVars: { '--color-accent': 'red' }, xterm: { background: 'red' } };
  const page = { id: 'page', cssVars: { '--color-accent': 'grey' }, xterm: { background: 'grey' } };
  const host = {
    Themes: {
      getSessionManifest: (context: { pinnedTheme: string | null }) => context.pinnedTheme ? pinned : page,
      getActiveTerminalManifest: () => page,
      onXtermThemeChange: (callback: () => void) => { listeners.add(callback); return () => { listeners.delete(callback); }; },
    },
    ThemeVarWriter: {
      applyVarDiff: (style: CSSStyleDeclaration, previous: Record<string, string>, next: Record<string, string>) => {
        Object.keys(previous).forEach(key => { if (!(key in next)) style.removeProperty(key); });
        Object.entries(next).forEach(([key, value]) => style.setProperty(key, value));
        return { values: next };
      },
    },
  };
  const framePinned = document.createElement('div'); framePinned.className = 'oc-frame';
  const frameOpen = document.createElement('div'); frameOpen.className = 'oc-frame';
  const before = document.documentElement.style.getPropertyValue('--color-accent');
  const releasePinned = bindTerminalTheme({ term: { options: {} } }, framePinned, { pinnedTheme: 'pin' }, host);
  const releaseOpen = bindTerminalTheme({ term: { options: {} } }, frameOpen, { pinnedTheme: null }, host);
  expect(framePinned.style.getPropertyValue('--color-accent')).toBe('red');
  expect(frameOpen.style.getPropertyValue('--color-accent')).toBe('grey');
  expect(document.documentElement.style.getPropertyValue('--color-accent')).toBe(before);
  releasePinned();
  releaseOpen();
});

test('two tabs in one frame paint their own panes, never the shared frame (#454)', () => {
  const a = { id: 'a', cssVars: { '--color-accent': 'red' } };
  const b = { id: 'b', cssVars: { '--color-accent': 'blue' } };
  const host = {
    Themes: {
      getSessionManifest: (context: { pinnedTheme: string | null }) => (context.pinnedTheme === 'a' ? a : b),
      getActiveTerminalManifest: () => null,
      onXtermThemeChange: () => () => {},
    },
    ThemeVarWriter: {
      applyVarDiff: (style: CSSStyleDeclaration, previous: Record<string, string>, next: Record<string, string>) => {
        Object.keys(previous).forEach((key) => { if (!(key in next)) style.removeProperty(key); });
        Object.entries(next).forEach(([key, value]) => style.setProperty(key, value));
        return { values: next };
      },
    },
  };
  const frame = document.createElement('div'); frame.className = 'oc-frame';
  const paneA = document.createElement('div'); paneA.setAttribute('data-theme-scope', '');
  const paneB = document.createElement('div'); paneB.setAttribute('data-theme-scope', '');
  const bodyA = document.createElement('div'); const bodyB = document.createElement('div');
  paneA.appendChild(bodyA); paneB.appendChild(bodyB); frame.append(paneA, paneB);
  const releaseA = bindTerminalTheme({}, bodyA, { pinnedTheme: 'a' }, host);
  const releaseB = bindTerminalTheme({}, bodyB, { pinnedTheme: 'b' }, host);
  expect(paneA.style.getPropertyValue('--color-accent')).toBe('red');
  expect(paneB.style.getPropertyValue('--color-accent')).toBe('blue');
  expect(frame.style.getPropertyValue('--color-accent')).toBe('');
  releaseA();
  expect(paneB.style.getPropertyValue('--color-accent')).toBe('blue');
  releaseB();
});

test('minimumContrastRatio is set from the fallback host helper, and resets on a light-to-dark swap (issue #967)', () => {
  const light = { id: 'light', xterm: { background: '#f1f2f3' } };
  const dark = { id: 'dark', xterm: { background: '#1e1e1e' } };
  let current = light;
  const listeners = new Set<() => void>();
  const host = {
    Themes: {
      getSessionManifest: () => current,
      getActiveTerminalManifest: () => dark,
      onXtermThemeChange: (callback: () => void) => { listeners.add(callback); return () => { listeners.delete(callback); }; },
    },
    TerminalBackgroundOpacity: {
      minimumContrastRatioForXtermTheme: (theme?: Record<string, string>) =>
        theme?.background === '#f1f2f3' ? 4.5 : 1,
    },
  };
  const client = { term: { options: {} as { theme?: Record<string, string>; minimumContrastRatio?: number } } };
  const frame = document.createElement('div'); frame.className = 'oc-frame';
  const release = bindTerminalTheme(client, frame, { pinnedTheme: 'light' }, host);
  expect(client.term.options.minimumContrastRatio).toBe(4.5);
  current = dark;
  listeners.forEach(listener => listener());
  expect(client.term.options.minimumContrastRatio).toBe(1);
  release();
  expect(client.term.options.minimumContrastRatio).toBe(1);
});
