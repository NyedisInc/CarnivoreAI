import { readTab, writeTab } from './tab-memory';

export type RowScope = 'global' | 'sessions';

export type Scope = RowScope | 'both';

export const SCOPES: readonly Scope[] = ['global', 'sessions', 'both'];

export const DEFAULT_SCOPE: Scope = 'both';

const KEY_PREFIX = 'scope.';

export function inScope(row: RowScope, scope: Scope): boolean {
  return scope === 'both' || scope === row;
}

export function readScope(surface: string): Scope {
  return readTab(KEY_PREFIX + surface, SCOPES, DEFAULT_SCOPE) as Scope;
}

export function writeScope(surface: string, scope: Scope): void {
  writeTab(KEY_PREFIX + surface, scope);
}
