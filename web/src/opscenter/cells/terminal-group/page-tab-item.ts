import { t } from '../../../lib/i18n/index.svelte';
import type { BrowserInfo } from '../../../lib/browser/api.svelte';
import type { PageInfo } from '../../../lib/browser/page-frame';
import type { OpenFileInfo } from '../../../lib/open-files/api.svelte';
import type { TabItem } from '../../shell/TabStrip.svelte';
import { pageTabState, type PageTabKind } from './page-tab-state.svelte';

export const PAGE_TAB_FAMILY = 'browser';

function glyphFor(kind: PageTabKind): string {
  return kind === 'file' ? 'files' : 'globe';
}

function fallbackName(kind: PageTabKind): string {
  if (kind === 'file') return t('files.screen.untitled');
  if (kind === 'gone') return t('opscenter.tabs.page_gone_name');
  return t('browser.page.untitled');
}

export function pageTabItem(tab: string, browserId: string): TabItem {
  const { kind, title } = pageTabState(browserId);
  return { id: tab, name: title || fallbackName(kind), family: PAGE_TAB_FAMILY, glyph: glyphFor(kind) };
}

export interface PageMenuRow {
  id: string;
  label: string;
}

export function pageMenuRows(
  pages: readonly PageInfo[],
  files: readonly OpenFileInfo[],
  browsers: readonly BrowserInfo[],
  here: ReadonlySet<string>,
): PageMenuRow[] {
  const rows: PageMenuRow[] = [
    ...files.map((f) => ({ id: f.id, label: f.title || t('files.screen.untitled') })),
    ...pages.map((p) => ({ id: p.id, label: p.title || t('browser.page.untitled') })),
    ...browsers.map((b) => ({ id: b.id, label: b.label || t('browser.page') })),
  ];
  return rows.filter((row) => !here.has(`page:${row.id}`));
}
