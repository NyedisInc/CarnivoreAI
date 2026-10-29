import { browserById, browsers } from '../../../lib/browser/api.svelte';
import { openPages, pageById } from '../../../lib/browser/pages.svelte';
import { fileById, openFiles } from '../../../lib/open-files/api.svelte';

export type PageTabKind = 'file' | 'page' | 'browser' | 'loading' | 'gone';

export interface PageTabState {
  kind: PageTabKind;
  title: string;
}

export function pageTabState(id: string): PageTabState {
  const file = fileById(id);
  if (file) return { kind: 'file', title: file.title ?? '' };
  const page = pageById(id);
  if (page) return { kind: 'page', title: page.title ?? '' };
  const browser = browserById(id);
  if (browser) return { kind: 'browser', title: browser.label ?? '' };
  const settled = openPages.status === 'ok' && openFiles.status === 'ok' && browsers.status === 'ok';
  return { kind: settled ? 'gone' : 'loading', title: '' };
}
