import type { LocalStateField } from '../../widgets/shell/widget-state.svelte';
import type { RootId } from './model';

export type FoldRecord = Readonly<Record<string, readonly string[]>>;

export type SectionChoice = Readonly<Partial<Record<RootId, boolean>>>;

export const FOLD_SCOPES_KEPT = 24;
export const FOLDS_PER_SCOPE = 400;
export const FILTER_MAX = 200;
const SELECTION_MAX = 2000;

const isBool = (value: unknown): value is boolean => typeof value === 'boolean';

const textUpTo = (max: number) => (value: unknown): value is string => typeof value === 'string' && value.length <= max;

export function isFoldRecord(value: unknown): value is FoldRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const entries = Object.entries(value as Record<string, unknown>);
  return entries.length <= FOLD_SCOPES_KEPT + 1 && entries.every(([, paths]) =>
    Array.isArray(paths) && paths.length <= FOLDS_PER_SCOPE && paths.every((path) => typeof path === 'string'));
}

export function isSectionChoice(value: unknown): value is SectionChoice {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  return Object.entries(value as Record<string, unknown>).every(([key, open]) => (key === 'workdir' || key === 'user') && isBool(open));
}

export function foldScope(root: RootId, folder: string): string {
  return root === 'user' ? 'user' : `project:${folder}`;
}

export function withFold(record: FoldRecord, scope: string, path: string, open: boolean): FoldRecord {
  const now = record[scope] ?? [];
  const paths = open ? [...now.filter((one) => one !== path), path].slice(-FOLDS_PER_SCOPE) : now.filter((one) => one !== path);
  const rest = Object.entries(record).filter(([key]) => key !== scope);
  const kept = paths.length ? [...rest, [scope, paths] as const] : rest;
  let projects = kept.filter(([key]) => key !== 'user').length;
  const out: Record<string, readonly string[]> = {};
  for (const [key, value] of kept) {
    if (key !== 'user' && projects > FOLD_SCOPES_KEPT) {
      projects -= 1;
      continue;
    }
    out[key] = value;
  }
  return out;
}

export function withoutScopes(record: FoldRecord, scopes: readonly string[]): FoldRecord {
  return Object.fromEntries(Object.entries(record).filter(([key]) => !scopes.includes(key)));
}

export function sectionIsOpen(choice: SectionChoice, root: RootId, hasProject: boolean): boolean {
  return choice[root] ?? (root === 'workdir' ? true : !hasProject);
}

function device<V>(def: V, valid: (value: unknown) => value is V): LocalStateField<V> {
  return { home: 'device', default: def, valid };
}

export const FILES_STATE = {
  folds: device<FoldRecord>({}, isFoldRecord),
  sections: device<SectionChoice>({}, isSectionChoice),
  'changes-open': device(true, isBool),
  filter: device('', textUpTo(FILTER_MAX)),
  'just-changes': device(false, isBool),
  'whole-file': device(false, isBool),
  'dot-files': device(true, isBool),
  'ignored-files': device(true, isBool),
  selection: device('', textUpTo(SELECTION_MAX)),
} as const;
