
export interface ThemeChoice {
  id: string;
  name: string;
}

interface Manifest {
  id: string;
  name?: string;
  cssVars?: Record<string, string>;
}

export interface ThemeRegistry {
  listAll?: () => Manifest[];
  getActiveGlobal?: () => Manifest | null;
}

const registry = (): ThemeRegistry | undefined => (globalThis as { Themes?: ThemeRegistry }).Themes;

const TOKEN_PREFIX = '--oc-';
const MAX_VALUE = 200;

export function themeChoices(host: ThemeRegistry | undefined = registry()): ThemeChoice[] {
  return (host?.listAll?.() ?? []).map((m) => ({ id: m.id, name: m.name || m.id }));
}

export function activeThemeId(host: ThemeRegistry | undefined = registry()): string | null {
  return host?.getActiveGlobal?.()?.id ?? null;
}

export function tokenNames(doc: Document = document): string[] {
  const names = new Set<string>();
  const walk = (rules: CSSRuleList): void => {
    for (const rule of Array.from(rules)) {
      const style = (rule as CSSStyleRule).style;
      if (style) for (const name of Array.from(style)) if (name.startsWith(TOKEN_PREFIX)) names.add(name);
      const nested = (rule as CSSGroupingRule).cssRules;
      if (nested) walk(nested);
    }
  };
  for (const sheet of Array.from(doc.styleSheets)) {
    try {
      walk(sheet.cssRules);
    } catch {
    }
  }
  return [...names].sort();
}

export function themeTokens(id: string, host: ThemeRegistry | undefined = registry(), doc: Document = document): Record<string, string> | null {
  const manifest = host?.listAll?.().find((m) => m.id === id);
  if (!manifest || !doc.body) return null;
  const probe = doc.createElement('div');
  const swatch = doc.createElement('span');
  probe.setAttribute('data-session-theme', id);
  probe.style.cssText = 'position:fixed;left:-9999px;width:0;height:0;visibility:hidden;pointer-events:none';
  for (const [name, value] of Object.entries(manifest.cssVars ?? {})) probe.style.setProperty(name, value);
  probe.appendChild(swatch);
  doc.body.appendChild(probe);
  try {
    const computed = getComputedStyle(probe);
    const out: Record<string, string> = {};
    for (const name of tokenNames(doc)) {
      const raw = computed.getPropertyValue(name).trim();
      if (!raw) continue;
      const value = asColor(raw, swatch);
      if (value.length <= MAX_VALUE) out[name] = value;
    }
    return out;
  } finally {
    probe.remove();
  }
}

function asColor(raw: string, swatch: HTMLElement): string {
  if (typeof CSS === 'undefined' || !CSS.supports?.('color', raw)) return raw;
  swatch.style.color = raw;
  const resolved = getComputedStyle(swatch).color;
  swatch.style.color = '';
  return resolved || raw;
}
