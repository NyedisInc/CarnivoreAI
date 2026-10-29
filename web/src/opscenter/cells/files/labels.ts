import { t } from '../../../lib/i18n/index.svelte';
import type { FxRow } from './model';

const PREFIX = 'opscenter.cell.files.';

export const GLOBAL_PATH = '~/.claude';

export function fk(key: string, vars?: Record<string, string | number>): string {
  return t(PREFIX + key, vars);
}

export function noteText(row: Extract<FxRow, { kind: 'note' }>, query: string): string {
  switch (row.code) {
    case 'loading': return fk('tree.loading');
    case 'empty': return row.root === 'user' && row.depth === 1 ? fk('empty.global') : fk('tree.empty');
    case 'error': return fk('tree.error', { detail: row.detail }) + (row.retry ? ` ${fk('tree.retry')}` : '');
    case 'no_session': return fk('tree.no_session');
    case 'no_match': return fk('tree.no_match', { q: query });
    case 'truncated': return fk('tree.truncated');
    case 'more_not_shown': return t('files.drawer.more_not_shown', { count: row.count });
  }
}

export function labelOf(row: FxRow, query: string): string {
  switch (row.kind) {
    case 'section': return fk(row.root === 'workdir' ? 'section.project' : 'section.global');
    case 'group': return fk('changed.group');
    case 'change': return row.file.path.split('/').pop() || row.file.path;
    case 'more': return fk('changed.more', { n: row.count });
    case 'node': return row.node.name;
    case 'note': return noteText(row, query);
  }
}

export function subOf(row: FxRow, projectName: string): string {
  if (row.kind === 'section') return row.root === 'workdir' ? projectName : GLOBAL_PATH;
  if (row.kind === 'group') return String(row.count);
  if (row.kind === 'change') return row.file.path.includes('/') ? row.file.path.slice(0, row.file.path.lastIndexOf('/')) : '';
  return '';
}

export function titleOf(row: FxRow): string {
  if (row.kind === 'change') return row.file.path;
  return row.kind === 'node' ? row.node.rel_path : '';
}
