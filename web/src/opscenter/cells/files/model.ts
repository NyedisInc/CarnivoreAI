import type { SessionGitFile } from '../../api/types';
import type { FxNode, RootId } from '../../../lib/file-drawer/tree-api';

export type { FxNode, RootId };

export interface Level {
  status: 'loading' | 'ready' | 'error';
  nodes: FxNode[];
  error: string | null;
}

export type NoteCode = 'loading' | 'empty' | 'error' | 'no_session' | 'no_match' | 'truncated' | 'more_not_shown';

export type FxRow =
  | { kind: 'section'; key: string; root: RootId; depth: 0; open: boolean }
  | { kind: 'group'; key: string; depth: 1; open: boolean; count: number }
  | { kind: 'change'; key: string; depth: 2; file: SessionGitFile }
  | { kind: 'more'; key: string; depth: 2; count: number }
  | { kind: 'node'; key: string; root: RootId; depth: number; node: FxNode; open: boolean }
  | {
      kind: 'note'; key: string; root: RootId; depth: number; code: NoteCode; detail: string; count: number;
      retry: string | null;
      level: string | null;
    };

export interface ViewOptions {
  showDot: boolean;
  showIgnored: boolean;
}

export interface BuildInput {
  roots: readonly RootId[];
  sectionOpen: Readonly<Record<RootId, boolean>>;
  levels: Readonly<Record<string, Level>>;
  expanded: ReadonlySet<string>;
  options: ViewOptions;
  hasProject: boolean;
  changes: readonly SessionGitFile[] | null;
  changesTruncated: number;
  changesOpen: boolean;
  changedOnly: boolean;
  changesCap: number;
  search: Readonly<Record<RootId, Level & { truncated: boolean }>> | null;
}

export function levelKey(root: RootId, path: string): string {
  return `${root}:${path}`;
}

export function rootOrder(showGlobal: boolean, topFolder: 'global' | 'project'): RootId[] {
  if (!showGlobal) return ['workdir'];
  return topFolder === 'project' ? ['workdir', 'user'] : ['user', 'workdir'];
}

export function shown(node: FxNode, options: ViewOptions): boolean {
  if (!options.showDot && node.name.startsWith('.')) return false;
  return options.showIgnored || !node.is_ignored;
}

function note(root: RootId, at: string, depth: number, code: NoteCode, detail = '', count = 0, retry: string | null = null, level: string | null = null): FxRow {
  return { kind: 'note', key: `note:${at}:${code}`, root, depth, code, detail, count, retry, level };
}

function walk(out: FxRow[], root: RootId, nodes: readonly FxNode[], depth: number, input: BuildInput, searching: boolean): void {
  for (const node of nodes) {
    if (node.kind === 'more') {
      out.push(note(root, levelKey(root, `${node.rel_path || ''}#more${depth}`), depth, 'more_not_shown', '', node.more_not_shown ?? 0));
      continue;
    }
    if (!shown(node, input.options)) continue;
    const key = levelKey(root, node.rel_path);
    const open = node.is_dir && (searching || input.expanded.has(key));
    out.push({ kind: 'node', key: `node:${key}`, root, depth, node, open });
    if (!open) continue;
    if (searching) {
      walk(out, root, node.children ?? [], depth + 1, input, true);
      continue;
    }
    pushLevel(out, root, node.rel_path, depth + 1, input);
  }
}

function pushLevel(out: FxRow[], root: RootId, path: string, depth: number, input: BuildInput): void {
  const key = levelKey(root, path);
  const level = input.levels[key];
  if (!level) out.push(note(root, key, depth, 'loading', '', 0, null, key));
  else if (level.status === 'loading') out.push(note(root, key, depth, 'loading'));
  else if (level.status === 'error') out.push(note(root, key, depth, 'error', level.error ?? '', 0, key));
  else if (!level.nodes.some((n) => n.kind === 'more' || shown(n, input.options))) out.push(note(root, key, depth, 'empty'));
  else walk(out, root, level.nodes, depth, input, false);
}

function pushChanges(out: FxRow[], input: BuildInput): void {
  const files = input.changes ?? [];
  const total = files.length + input.changesTruncated;
  if (total === 0) return;
  if (!input.changedOnly) out.push({ kind: 'group', key: 'group:changes', depth: 1, open: input.changesOpen, count: total });
  if (!input.changedOnly && !input.changesOpen) return;
  const cap = input.changedOnly ? files.length : Math.min(files.length, input.changesCap);
  for (const file of files.slice(0, cap)) {
    out.push({ kind: 'change', key: `change:${file.path}:${file.index}${file.worktree}`, depth: 2, file });
  }
  const rest = total - cap;
  if (rest > 0) out.push({ kind: 'more', key: 'more:changes', depth: 2, count: rest });
}

export function buildRows(input: BuildInput): FxRow[] {
  const out: FxRow[] = [];
  for (const root of input.roots) {
    const open = input.sectionOpen[root];
    out.push({ kind: 'section', key: `section:${root}`, root, depth: 0, open });
    if (!open) continue;
    if (root === 'workdir' && !input.hasProject) {
      out.push(note(root, 'workdir', 1, 'no_session'));
      continue;
    }
    if (input.search) {
      const found = input.search[root];
      if (found.status !== 'ready') out.push(note(root, `find:${root}`, 1, found.status === 'error' ? 'error' : 'loading', found.error ?? ''));
      else if (found.nodes.length === 0) out.push(note(root, `find:${root}`, 1, 'no_match'));
      else walk(out, root, found.nodes, 1, input, true);
      if (found.status === 'ready' && found.truncated) out.push(note(root, `find:${root}`, 1, 'truncated'));
      continue;
    }
    if (root === 'workdir') pushChanges(out, input);
    if (root === 'workdir' && input.changedOnly) continue;
    pushLevel(out, root, '', 1, input);
  }
  return out;
}

export function unreadLevels(rows: readonly FxRow[]): string[] {
  return rows.flatMap((row) => (row.kind === 'note' && row.level ? [row.level] : []));
}

export function splitLevelKey(key: string): [RootId, string] {
  const at = key.indexOf(':');
  return [key.slice(0, at) as RootId, key.slice(at + 1)];
}

export function focusable(row: FxRow): boolean {
  return row.kind !== 'note' || row.retry !== null;
}

export function stepFocus(rows: readonly FxRow[], key: string | null, delta: number): string | null {
  const keys = rows.filter(focusable).map((row) => row.key);
  if (keys.length === 0) return null;
  const at = key === null ? -1 : keys.indexOf(key);
  if (at < 0) return keys[0]!;
  if (delta === Infinity) return keys[keys.length - 1]!;
  if (delta === -Infinity) return keys[0]!;
  return keys[Math.max(0, Math.min(keys.length - 1, at + delta))]!;
}

export function parentOf(rows: readonly FxRow[], key: string): string | null {
  const at = rows.findIndex((row) => row.key === key);
  if (at < 0) return null;
  const depth = rows[at]!.depth;
  for (let i = at - 1; i >= 0; i -= 1) {
    const row = rows[i]!;
    if (row.depth < depth && focusable(row)) return row.key;
  }
  return null;
}
