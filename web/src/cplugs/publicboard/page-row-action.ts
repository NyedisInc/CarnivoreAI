import { openModal, t } from '../sdk';
import type { PageRowAction, PageRowActionPage } from '../sdk';
import ShareLinkModal from './ShareLinkModal.svelte';

export const SHARE_ROW_ACTION_ID = 'share-link';

const BOARD_PAGE_PATH = '/static/popout.html';

export function boardSlugOfPage(page: PageRowActionPage): string | null {
  let url: URL;
  try {
    url = new URL(page.src ?? page.key.replace(/^app:/, ''), globalThis.location.origin);
  } catch {
    return null;
  }
  const slug = url.searchParams.get('board');
  if (url.pathname !== BOARD_PAGE_PATH || url.searchParams.get('tab') !== 'reviewboard' || !slug) return null;
  return /[/\\]|\.\./.test(slug) ? null : slug;
}

export function sharePageRowAction(enabled: () => boolean): PageRowAction {
  return {
    plugin: 'publicboard',
    id: SHARE_ROW_ACTION_ID,
    label: () => t('cplug.publicboard.share.row'),
    enabled,
    targetOf: boardSlugOfPage,
    run: (slug) => void openModal(ShareLinkModal, { slug }),
  };
}
