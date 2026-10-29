<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { Button } from '../base';
  import ModalShell from '../launchpad/ModalShell.svelte';
  import { ApiError } from '../../opscenter/api/auth.svelte';
  import { openConversation } from '../conversation-open/open';
  import { openSession } from '../../cplugs/sdk/sessions.svelte';
  import { t } from '../i18n/index.svelte';
  import type { ConversationTarget } from '../conversation-open/open';
  import { branchBookmark, fetchContext, WINDOW_SIZE, type ContextMark, type ContextMessage, type ContextRequest } from './context-api';
  import type { HitBookmark } from './deepsearch-api';
  import { hitTime } from './when';

  interface Props {
    close: (value: null) => void;
    title: string;
    request: ContextRequest;
    target: ConversationTarget;
    hostLabel: string | null;
    bookmark: HitBookmark | null;
    focus: 'hit' | 'bookmark';
    hitLine: number | null;
  }
  let { close, title, request, target, hostLabel, bookmark, focus, hitLine }: Props = $props();

  type Phase = 'loading' | 'ready' | 'failed' | 'gone';
  let phase = $state<Phase>('loading');
  let messages = $state.raw<ContextMessage[]>([]);
  let marks = $state.raw<ContextMark[]>([]);
  let anchor = $state<number | null>(null);
  let hasBefore = $state(false);
  let hasAfter = $state(false);
  let loadingBefore = $state(false);
  let loadingAfter = $state(false);
  let note = $state('');
  let restoring = $state(false);
  let bodyEl = $state<HTMLElement | null>(null);
  let restoreEl = $state<HTMLElement | null>(null);
  const abort = new AbortController();

  const remote = $derived(request.hostKey !== null && request.hostKey !== 'local');
  const restorable = $derived(bookmark !== null && bookmark.id !== null && !remote);

  function paging(cursor: { beforeLine?: number; afterLine?: number }): ContextRequest {
    return { conversationId: request.conversationId, fileKind: request.fileKind, hostKey: request.hostKey, ...cursor };
  }

  function addMarks(found: ContextMark[]): void {
    const seen = new Set(marks.map((m) => `${m.id ?? 'r'}:${m.at}`));
    const fresh = found.filter((m) => !seen.has(`${m.id ?? 'r'}:${m.at}`));
    if (fresh.length > 0) marks = [...marks, ...fresh];
  }

  function failure(err: unknown): Phase {
    return err instanceof ApiError && err.status === 404 ? 'gone' : 'failed';
  }

  async function settle(): Promise<void> {
    await tick();
    const root = bodyEl;
    if (!root) return;
    if (focus === 'bookmark' && bookmark) {
      const marker = [...root.querySelectorAll<HTMLElement>('[data-mark-at]')].find((el) => el.dataset.markAt === bookmark.at);
      marker?.scrollIntoView?.({ block: 'center' });
      restoreEl?.focus();
      return;
    }
    const landing = anchor === null ? null : messages.find((m) => m.line >= anchor!);
    if (landing) root.querySelector<HTMLElement>(`[data-line="${landing.line}"]`)?.scrollIntoView?.({ block: 'center' });
  }

  async function load(): Promise<void> {
    try {
      const w = await fetchContext(request, WINDOW_SIZE, WINDOW_SIZE, abort.signal);
      if (abort.signal.aborted) return;
      messages = w.messages;
      anchor = w.anchor;
      hasBefore = w.hasBefore;
      hasAfter = w.hasAfter;
      addMarks(w.bookmarks);
      phase = w.messages.length > 0 ? 'ready' : 'gone';
      await settle();
    } catch (err) {
      if (!abort.signal.aborted) phase = failure(err);
    }
  }

  async function earlier(): Promise<void> {
    const first = messages[0];
    if (!first || !hasBefore || loadingBefore) return;
    loadingBefore = true;
    try {
      const before = bodyEl?.scrollHeight ?? 0;
      const w = await fetchContext(paging({ beforeLine: first.line }), WINDOW_SIZE, 1, abort.signal);
      if (abort.signal.aborted) return;
      messages = [...w.messages, ...messages];
      hasBefore = w.hasBefore;
      addMarks(w.bookmarks);
      await tick();
      if (bodyEl) bodyEl.scrollTop += bodyEl.scrollHeight - before;
    } catch (err) {
      if (!abort.signal.aborted) note = t('deepsearch.context.failed');
    } finally {
      loadingBefore = false;
    }
  }

  async function later(): Promise<void> {
    const last = messages[messages.length - 1];
    if (!last || !hasAfter || loadingAfter) return;
    loadingAfter = true;
    try {
      const w = await fetchContext(paging({ afterLine: last.line }), 1, WINDOW_SIZE, abort.signal);
      if (abort.signal.aborted) return;
      messages = [...messages, ...w.messages];
      hasAfter = w.hasAfter;
      addMarks(w.bookmarks);
    } catch (err) {
      if (!abort.signal.aborted) note = t('deepsearch.context.failed');
    } finally {
      loadingAfter = false;
    }
  }

  function onScroll(): void {
    const el = bodyEl;
    if (!el || phase !== 'ready') return;
    if (el.scrollTop < 48) void earlier();
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 48) void later();
  }

  async function openAgent(): Promise<void> {
    note = '';
    const outcome = await openConversation(target);
    if (outcome === 'switched' || outcome === 'page') close(null);
    else if (outcome === 'failed') note = t('deepsearch.open_failed');
    else note = remote ? t('deepsearch.on_computer', { computer: hostLabel ?? request.hostKey ?? '' }) : t('deepsearch.no_session');
  }

  async function restore(): Promise<void> {
    if (!bookmark || bookmark.id === null || restoring) return;
    restoring = true;
    note = '';
    try {
      const made = await branchBookmark(bookmark.id);
      if (made.sessionId) await openSession(made.sessionId, made.tmuxName);
      close(null);
    } catch (err) {
      note = t('deepsearch.context.restore_failed', { error: err instanceof Error ? err.message : '' });
      restoring = false;
    }
  }

  function markText(m: ContextMark): string {
    return m.label ? t('deepsearch.context.marker', { label: m.label, time: hitTime(m.at) }) : t('deepsearch.context.marker_unnamed', { time: hitTime(m.at) });
  }

  function restoreLine(): string {
    return markText({ id: bookmark?.id ?? null, label: bookmark?.label ?? '', at: bookmark?.at ?? '', afterLine: null });
  }

  const topMarks = $derived(hasBefore ? [] : marks.filter((m) => m.afterLine === null));

  onMount(() => {
    void load();
    return () => abort.abort();
  });
</script>

<ModalShell {title} overlayClass="dps-ctx-modal" onCancel={() => close(null)}>
  {#snippet children()}
    {#if hostLabel}<p class="dps-ctx__host" data-testid="context-host">{hostLabel}</p>{/if}
    {#if phase === 'loading'}
      <p class="dps-ctx__status" role="status">{t('deepsearch.context.loading')}</p>
    {:else if phase === 'failed'}
      <p class="dps-ctx__status dps-ctx__status--bad" role="alert">{t('deepsearch.context.failed')}</p>
    {:else if phase === 'gone'}
      <p class="dps-ctx__status" role="status">{t('deepsearch.context.gone')}</p>
    {:else}
      <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
      <div class="dps-ctx__scroll" bind:this={bodyEl} onscroll={onScroll} role="region" tabindex="0"
        aria-label={t('deepsearch.context.label')} data-testid="context-scroll">
        {#if hasBefore}
          <Button variant="row" data-ctx-more disabled={loadingBefore} onclick={() => void earlier()}>{t('deepsearch.context.earlier')}</Button>
        {/if}
        {#each topMarks as m (`${m.id ?? 'r'}:${m.at}`)}
          <p class="dps-ctx__mark" data-mark-at={m.at}>{markText(m)}</p>
        {/each}
        {#each messages as m (m.line)}
          <div class="dps-ctx__msg" class:is-hit={m.line === (focus === 'hit' ? anchor : hitLine)} data-line={m.line} data-role={m.role}>
            <p class="dps-ctx__who">{t(`deepsearch.kind.${m.kind}`)}{#if hitTime(m.at)}{' · '}{hitTime(m.at)}{/if}</p>
            <p class="dps-ctx__text">{m.text}</p>
          </div>
          {#each marks.filter((x) => x.afterLine === m.line) as mk (`${mk.id ?? 'r'}:${mk.at}`)}
            <p class="dps-ctx__mark" data-mark-at={mk.at}>{markText(mk)}</p>
          {/each}
        {/each}
        {#if hasAfter}
          <Button variant="row" data-ctx-more disabled={loadingAfter} onclick={() => void later()}>{t('deepsearch.context.later')}</Button>
        {/if}
      </div>
    {/if}
  {/snippet}
  {#snippet footer()}
    {#if note}<p class="dps-ctx__note" role="alert" data-testid="context-note">{note}</p>{/if}
    {#if restorable}<p class="dps-ctx__restore-line" data-testid="context-restore-line">{restoreLine()}</p>{/if}
    <Button onclick={() => close(null)}>{t('deepsearch.context.close')}</Button>
    {#if restorable}
      <Button variant="confirm" bind:element={restoreEl} disabled={restoring} data-testid="context-restore"
        onclick={() => void restore()}>{restoring ? t('deepsearch.context.restoring') : t('deepsearch.context.restore')}</Button>
    {/if}
    <Button variant="confirm" data-testid="context-open-agent" onclick={() => void openAgent()}>{t('deepsearch.open_agent')}</Button>
  {/snippet}
</ModalShell>

<style>
  @layer components {
    :global(.dps-ctx-modal .modal-content) {
      width: min(720px, 94vw);
      max-width: 94vw;
      border-radius: 2px;
      font-family: var(--font-mono);
    }

    :global(.dps-ctx-modal .modal-body) {
      padding: 0;
    }

    :global(.dps-ctx-modal .modal-footer) {
      flex-wrap: wrap;
      align-items: center;
    }

    .dps-ctx__restore-line {
      flex: 1 0 100%;
      margin: 0;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-hint);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .dps-ctx__scroll {
      max-height: min(60vh, 560px);
      overflow-y: auto;
      overscroll-behavior: contain;
      font-size: var(--oc-fs-body);
      line-height: 1.45;
    }

    .dps-ctx__host,
    .dps-ctx__status {
      margin: 0;
      padding: var(--oc-space-2) var(--oc-space-3);
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-hint);
    }

    .dps-ctx__status--bad {
      color: var(--oc-coral);
    }

    .dps-ctx__msg {
      padding: var(--oc-space-2) var(--oc-space-3);
      color: var(--oc-text-secondary);
    }

    .dps-ctx__msg + .dps-ctx__msg {
      border-top: var(--oc-border) solid var(--oc-line-faint);
    }

    .dps-ctx__msg.is-hit {
      background: var(--oc-ground-hover);
      color: var(--oc-text-primary);
      box-shadow: inset 2px 0 0 var(--oc-orange);
    }

    .dps-ctx__who {
      margin: 0 0 2px;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .dps-ctx__text {
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .dps-ctx__mark {
      margin: 0;
      padding: var(--oc-space-1) var(--oc-space-3);
      border-block: var(--oc-border) dashed var(--oc-line-rule);
      color: var(--oc-cyan);
      font-size: var(--oc-fs-hint);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .dps-ctx__scroll :global([data-ctx-more]) {
      width: 100%;
      max-width: none;
      --_btn-h: auto;
      --_btn-pad: var(--oc-space-3);
      --_btn-fs: var(--oc-fs-hint);
      --_btn-ink: var(--oc-text-dim);
      padding-block: var(--oc-space-1);
      border-radius: 0;
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
    }

    .dps-ctx__note {
      flex: 1 0 100%;
      margin: 0 0 var(--oc-space-1);
      color: var(--oc-coral);
      font-size: var(--oc-fs-hint);
    }
  }

  :global(.dps-ctx-modal .modal-footer) {
    gap: 8px;
    padding: 12px 14px 14px;
  }

  :global(.dps-ctx-modal .modal-footer .modal-btn) {
    padding: 7px 16px;
    font-size: 13px;
  }

  :global(.dps-ctx-modal .modal-footer .modal-btn:disabled) {
    opacity: 0.45;
    cursor: not-allowed;
  }

  @media (pointer: coarse), (max-width: 600px) {
    :global(.dps-ctx-modal .modal-footer .modal-btn) {
      min-height: 44px;
    }
  }

  @media (max-width: 600px) {
    :global(.dps-ctx-modal .modal-footer .modal-btn) {
      flex: 0 0 auto;
      padding-inline: 8px;
      white-space: nowrap;
    }

    :global(.dps-ctx-modal .modal-footer .modal-btn-secondary) {
      order: 1;
    }
  }
</style>
