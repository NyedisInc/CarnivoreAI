import '../../../client/js/theme-scheme.js';
import { registry, type ThemeRegistry } from '../cplugs/sdk/themes';

interface ThemeSchemeApi {
  SCHEME_VAR: string;
  withColorScheme(vars: Record<string, string>): Record<string, string>;
  useCanvas(make: (() => HTMLCanvasElement) | null): void;
}

function api(): ThemeSchemeApi | null {
  const found = (globalThis as { ThemeScheme?: ThemeSchemeApi }).ThemeScheme;
  return found && typeof found.withColorScheme === 'function' ? found : null;
}

api()?.useCanvas(() => document.createElement('canvas'));

export function withColorScheme(vars: Record<string, string>): Record<string, string> {
  return api()?.withColorScheme(vars) ?? vars;
}

export function frameScheme(id: string | null | undefined, host: ThemeRegistry | undefined = registry()): string | undefined {
  const manifest = id ? host?.listAll?.().find((m) => m.id === id) : host?.getActiveGlobal?.();
  return manifest ? withColorScheme(manifest.cssVars ?? {})['--color-scheme'] : undefined;
}
