import { auth as authState } from '../../opscenter/api/auth.svelte';
import { openModal } from '../modal';
import { t } from '../i18n/index.svelte';
import ContextModal from './ContextModal.svelte';
import { parseLink, type ContextLink } from './context-link';

let started = false;

function show(link: ContextLink): void {
  void openModal(ContextModal as never, {
    title: t('deepsearch.link_title'),
    request: { conversationId: link.conversationId, fileKind: link.fileKind, hostKey: link.hostKey, line: link.line },
    target: { conversationId: link.conversationId, sessionUuid: null, projectId: null },
    hostLabel: null,
    bookmark: null,
    focus: 'hit',
    hitLine: link.line,
  } as unknown as Record<string, unknown>);
}

function clearHash(): void {
  const { pathname, search } = window.location;
  window.history.replaceState(window.history.state, '', `${pathname}${search}`);
}

export function openLinkFromHash(): void {
  const link = parseLink(window.location.hash);
  if (!link || authState.state !== 'signed-in') return;
  clearHash();
  show(link);
}

export function startContextLinks(): void {
  if (started || typeof window === 'undefined') return;
  started = true;
  window.addEventListener('hashchange', openLinkFromHash);
  $effect.root(() => {
    $effect(() => {
      void authState.state;
      openLinkFromHash();
    });
  });
}
