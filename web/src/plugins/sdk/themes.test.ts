/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { activeThemeId, themeChoices, themeTokens, tokenNames, type ThemeRegistry } from './themes';

const registry: ThemeRegistry = {
  listAll: (): ReturnType<NonNullable<ThemeRegistry['listAll']>> => [
    { id: 'carnivore', name: 'Carnivore', cssVars: { '--color-bg-page': '#02161e' } },
    { id: 'dracula', name: 'Dracula', cssVars: { '--color-bg-page': '#1e1f29', '--color-accent': '#bd93f9' } },
    { id: 'nameless', cssVars: {} },
  ],
  getActiveGlobal: () => ({ id: 'dracula' }),
};

afterEach(() => {
  document.head.innerHTML = '';
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
});

describe('the list and the active theme', () => {
  it('lists every theme the registry has, naming one by its id when it has no name', () => {
    expect(themeChoices(registry)).toEqual([{ id: 'carnivore', name: 'Carnivore' }, { id: 'dracula', name: 'Dracula' }, { id: 'nameless', name: 'nameless' }]);
  });
  it('is empty before the registry loads, and the active id is null', () => {
    expect(themeChoices(undefined)).toEqual([]);
    expect(activeThemeId(undefined)).toBeNull();
  });
  it('names the theme the app wears', () => expect(activeThemeId(registry)).toBe('dracula'));
});

describe('tokenNames reads the --oc-* custom properties from the loaded stylesheets', () => {
  it('finds them under :root, [data-session-theme], nested rules and layers, once each, and skips other variables', () => {
    document.head.innerHTML = '<style>:root, [data-session-theme] { --oc-ground-page: var(--color-bg-page, #000); --oc-orange: #f00; --color-x: red; } @media (min-width: 1px) { .a { --oc-text-primary: #fff; } } .b { --oc-orange: #00f; }</style>';
    expect(tokenNames(document)).toEqual(['--oc-ground-page', '--oc-orange', '--oc-text-primary']);
  });
});

describe('themeTokens', () => {
  function stubBrowser(seen: { probe?: HTMLElement; scope?: string | null; cssVars?: Record<string, string> }): void {
    document.head.innerHTML = '<style>:root { --oc-ground-page: x; --oc-orange: y; --oc-long: z; --oc-empty: w; }</style>';
    vi.stubGlobal('getComputedStyle', (el: Element) => {
      if (el.hasAttribute('data-session-theme')) {
        seen.probe = el as HTMLElement;
        seen.scope = el.getAttribute('data-session-theme');
        seen.cssVars = { '--color-bg-page': (el as HTMLElement).style.getPropertyValue('--color-bg-page') };
      }
      return {
        color: 'rgb(9, 9, 9)',
        getPropertyValue: (name: string) => ({
          '--oc-ground-page': ` ${(el as HTMLElement).style?.getPropertyValue('--color-bg-page') ?? ''} `,
          '--oc-orange': 'color-mix(in srgb, #bd93f9 50%, black)', '--oc-long': 'x'.repeat(201), '--oc-empty': '',
        } as Record<string, string>)[name] ?? '',
      };
    });
  }

  it('applies the chosen theme\'s manifest to a probe scoped with data-session-theme, reads the tokens back, and removes the probe', () => {
    const seen: { probe?: HTMLElement; scope?: string | null; cssVars?: Record<string, string> } = {};
    stubBrowser(seen);
    vi.stubGlobal('CSS', { supports: (_p: string, v: string) => v.startsWith('color-mix') });
    const out = themeTokens('dracula', registry, document);
    expect(seen.scope).toBe('dracula');
    expect(seen.cssVars).toEqual({ '--color-bg-page': '#1e1f29' });
    expect(out?.['--oc-ground-page']).toBe('#1e1f29');
    expect(out?.['--oc-orange']).toBe('rgb(9, 9, 9)');
    expect(out).not.toHaveProperty('--oc-long');
    expect(out).not.toHaveProperty('--oc-empty');
    expect(document.querySelector('[data-session-theme]')).toBeNull();
  });

  it('is null for a theme the registry does not have, and for no registry', () => {
    expect(themeTokens('gone', registry, document)).toBeNull();
    expect(themeTokens('dracula', undefined, document)).toBeNull();
  });
});
