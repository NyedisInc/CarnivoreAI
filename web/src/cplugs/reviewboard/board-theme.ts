import { t, themeChoices, themeTokens, type ThemeChoice } from '../sdk';

export const THEME_KEY = 'carnivore.reviewboard.theme';

export function readThemeChoice(): string {
  try {
    return localStorage.getItem(THEME_KEY) ?? '';
  } catch {
    return '';
  }
}

export function writeThemeChoice(id: string): void {
  try {
    if (id) localStorage.setItem(THEME_KEY, id);
    else localStorage.removeItem(THEME_KEY);
  } catch {
  }
}

export function effectiveTheme(choice: string, choices: readonly ThemeChoice[], active: string | null): string | null {
  return choice && choices.some((c) => c.id === choice) ? choice : active;
}

export interface ThemeSource {
  id: string;
  label: string;
  list(): ThemeChoice[];
  tokens(id: string): Record<string, string> | null;
}

export interface ThemeGroup {
  source: ThemeSource;
  choices: ThemeChoice[];
}

export const APP_THEME_SOURCE: ThemeSource = {
  id: 'app',
  get label() {
    return t('cplug.reviewboard.theme.source_app');
  },
  list: () => themeChoices(),
  tokens: (id) => themeTokens(id),
};

const sources: ThemeSource[] = [APP_THEME_SOURCE];

export function registerThemeSource(source: ThemeSource): () => void {
  const at = sources.findIndex((s) => s.id === source.id);
  if (at >= 0) sources[at] = source;
  else sources.push(source);
  return () => {
    const now = sources.indexOf(source);
    if (now >= 0) sources.splice(now, 1);
  };
}

export function themeGroups(): ThemeGroup[] {
  return sources.map((source) => ({ source, choices: source.list() })).filter((g) => g.choices.length > 0);
}

export function flatChoices(groups: readonly ThemeGroup[]): ThemeChoice[] {
  const seen = new Set<string>();
  return groups.flatMap((g) => g.choices).filter((c) => !seen.has(c.id) && seen.add(c.id));
}

export function tokensFor(id: string): Record<string, string> | null {
  const owner = sources.find((s) => s.list().some((c) => c.id === id));
  return owner ? owner.tokens(id) : null;
}
