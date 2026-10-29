
<script lang="ts">
  import { tick } from 'svelte';
  import { truncatedTip } from '../../../lib/tooltip/truncated-tip';
  import type { CrosstalkThread } from '../../../lib/crosstalk/history/history-model';
  import { t } from '../../../lib/i18n/index.svelte';
  import Button from '../../../lib/base/Button.svelte';
  import {
    ageText, COUNT_MIN_WIDTH, delivery, direction, fullTime, isNew, stepIndex, type SeenMarks,
  } from './model';

  interface Props {
    threads: CrosstalkThread[];
    marks: SeenMarks;
    baseline: number;
    nowMs: number;
    width: number;
    selected: string | null;
    returnTo: string | null;
    more: boolean;
    wrap: boolean;
    onopen: (thread: string) => void;
    onmore: () => void;
    onreturned: () => void;
  }

  let { threads, marks, baseline, nowMs, width, selected, returnTo, more, wrap, onopen, onmore, onreturned }: Props = $props();

  let active = $state<string | null>(null);
  let listEl = $state<HTMLUListElement | null>(null);

  const stop = $derived(threads.some((t) => t.thread === active) ? active : selected ?? threads[0]?.thread ?? null);
  const showCount = $derived(width >= COUNT_MIN_WIDTH);

  function pageRows(): number {
    return Math.max(1, Math.floor((listEl?.clientHeight ?? 160) / 40));
  }

  function focusRow(thread: string): void {
    active = thread;
    listEl?.querySelector<HTMLElement>(`[data-thread="${CSS.escape(thread)}"]`)?.focus();
  }

  function onKey(event: KeyboardEvent, index: number): void {
    if (event.key === 'Enter' || event.key === ' ' || event.key === 'ArrowRight') {
      event.preventDefault();
      onopen(threads[index]!.thread);
      return;
    }
    const next = stepIndex(event.key, index, threads.length, pageRows());
    if (next === null) return;
    event.preventDefault();
    focusRow(threads[next]!.thread);
  }

  $effect(() => {
    const thread = returnTo;
    if (!thread) return;
    void tick().then(() => {
      if (threads.some((t) => t.thread === thread)) focusRow(thread);
      onreturned();
    });
  });

  $effect(() => {
    const thread = selected;
    if (!thread || !listEl) return;
    void tick().then(() => listEl?.querySelector(`[data-thread="${CSS.escape(thread)}"]`)?.scrollIntoView({ block: 'nearest' }));
  });
</script>

<ul class="xr-list" role="listbox" aria-label={t('crosstalk.history.threads')} bind:this={listEl}>
  {#each threads as thread, index (thread.thread)}
    {@const way = direction(thread)}
    {@const fresh = isNew(thread, marks, baseline)}
    {@const trouble = delivery(thread.last_status, way.to.name)}
    <li class="xr-row" class:xr-row--new={fresh} class:xr-row--on={selected === thread.thread} role="presentation">
      <button type="button" class="xr-hit" data-btn="row" role="option" data-thread={thread.thread} data-crosstalk-open={thread.thread}
        aria-selected={selected === thread.thread} tabindex={stop === thread.thread ? 0 : -1}
        onclick={() => { active = thread.thread; onopen(thread.thread); }}
        onkeydown={(event) => onKey(event, index)} onfocus={() => (active = thread.thread)}>
        {#if wrap}
          <span class="xr-w">
            <span class="xr-mark" aria-hidden="true"></span>
            <span class="xr-w__main">
              <span class="xr-w__pair">{#if fresh}<span class="xr-sr">{t('crosstalk.widget.new_prefix')} </span>{/if}<bdi class="xr-wn xr-wn--from">{way.from.name}</bdi> <span class="xr-wn"><span class="xr-arrow" aria-label={t('crosstalk.widget.wrote_to')}>→</span> <bdi>{way.to.name}</bdi></span></span>
              {#if trouble}<span class="xr-w__trouble" class:xr-trouble--bad={trouble.bad}>{trouble.word}</span>{/if}
              <span class="xr-w__preview">{thread.last_preview}</span>
            </span>
            <span class="xr-w__meta">
              <time class="xr-age" datetime={new Date(thread.last_at * 1000).toISOString()} title={fullTime(thread.last_at)}>{ageText(thread.last_at, nowMs)}</time>
              {#if showCount}<span class="xr-count">{t(thread.message_count === 1 ? 'crosstalk.widget.messages_one' : 'crosstalk.widget.messages_many', { n: thread.message_count })}</span>{/if}
            </span>
          </span>
        {:else}
        <span class="xr-line">
          <span class="xr-mark" aria-hidden="true"></span>
          {#if fresh}<span class="xr-sr">{t('crosstalk.widget.new_prefix')} </span>{/if}
          <bdi class="xr-name xr-name--from" use:truncatedTip={`${way.from.name}${way.from.project_name ? ` (${way.from.project_name})` : ''}`}>{way.from.name}</bdi>
          <span class="xr-arrow" aria-label={t('crosstalk.widget.wrote_to')}>→</span>
          <bdi class="xr-name xr-name--to" use:truncatedTip={`${way.to.name}${way.to.project_name ? ` (${way.to.project_name})` : ''}`}>{way.to.name}</bdi>
          <time class="xr-age" datetime={new Date(thread.last_at * 1000).toISOString()} title={fullTime(thread.last_at)}>{ageText(thread.last_at, nowMs)}</time>
        </span>
        <span class="xr-line xr-line--sub">
          {#if trouble}<span class="xr-trouble" class:xr-trouble--bad={trouble.bad}>{trouble.word}:</span>{/if}
          <span class="xr-preview">{thread.last_preview}</span>
          {#if showCount}<span class="xr-count">{t(thread.message_count === 1 ? 'crosstalk.widget.messages_one' : 'crosstalk.widget.messages_many', { n: thread.message_count })}</span>{/if}
        </span>
        {/if}
      </button>
    </li>
  {/each}
  {#if more}
    <li class="xr-row xr-row--more" role="presentation">
      <Button data-crosstalk-more onclick={onmore}>{t('crosstalk.widget.older_conversations')}</Button>
    </li>
  {/if}
</ul>

<style>
  @layer components {
    .xr-list { flex: 1 1 auto; min-height: 0; margin: 0; padding: 0; overflow-y: auto; list-style: none; }
    .xr-row { box-shadow: inset 0 -1px 0 var(--oc-line-faint, var(--oc-line-panel)); }

    .xr-hit { flex-direction: column; align-items: stretch; gap: var(--oc-space-0-5); width: 100%; min-width: 0; padding: var(--oc-space-1) var(--oc-space-2) calc(var(--oc-space-1) + var(--oc-border)) 0; border-radius: 0; color: inherit; font: inherit; }
    .xr-hit:hover { background: var(--oc-ground-hover); }
    .xr-row--on .xr-hit { background: var(--oc-ground-raised); }
    .xr-row--on .xr-hit:has(.xr-w) { box-shadow: inset 2px 0 0 var(--oc-text-secondary); }

    .xr-line { display: flex; align-items: baseline; gap: var(--oc-space-1-5); min-width: 0; white-space: nowrap; }
    .xr-mark { flex: none; width: 14px; align-self: center; height: 6px; }
    .xr-row--new .xr-mark { background: radial-gradient(circle at 8px 3px, var(--oc-green) 0 3px, transparent 3.5px); }
    .xr-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }

    .xr-name { flex: 0 1 auto; min-width: 2ch; max-width: 50%; overflow: hidden; text-overflow: ellipsis; color: var(--oc-text-secondary); }
    .xr-name--from { color: var(--oc-text-primary); }
    .xr-row--new .xr-name--from { color: var(--oc-text-bright, var(--oc-text-primary)); font-weight: 600; }
    .xr-arrow { flex: none; color: var(--oc-text-dim); }
    .xr-age { flex: none; margin-left: auto; padding-left: var(--oc-space-1); color: var(--oc-text-dim); font-size: var(--oc-fs-label); }
    .xr-row--new .xr-age { color: var(--oc-green); }

    .xr-line--sub { padding-left: calc(var(--oc-space-4) + var(--oc-space-1)); font-size: var(--oc-fs-label); }
    .xr-trouble { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; color: var(--oc-yellow); }
    .xr-trouble--bad { color: var(--oc-coral); }
    .xr-preview { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; color: var(--oc-text-dim); }
    .xr-count { flex: none; color: var(--oc-text-dim); }

    .xr-w { display: flex; align-items: flex-start; gap: var(--oc-space-1-5); min-width: 0; }
    .xr-w .xr-mark { margin-top: calc(var(--oc-space-1) + var(--oc-border)); }
    .xr-w__main { display: flex; flex-direction: column; gap: var(--oc-space-0-5); flex: 1 1 auto; min-width: 0; }
    .xr-w__pair { color: var(--oc-text-secondary); white-space: normal; overflow-wrap: anywhere; line-height: 1.35; }
    .xr-wn { display: inline-block; max-width: 100%; vertical-align: top; }
    .xr-wn--from { color: var(--oc-text-primary); }
    .xr-row--new .xr-wn--from { color: var(--oc-text-bright, var(--oc-text-primary)); font-weight: 600; }
    .xr-w__trouble { color: var(--oc-yellow); font-size: var(--oc-fs-label); white-space: normal; overflow-wrap: anywhere; }
    .xr-w__trouble.xr-trouble--bad { color: var(--oc-coral); }
    .xr-w__preview { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--oc-text-dim); font-size: var(--oc-fs-label); }
    .xr-w__meta { display: flex; flex-direction: column; align-items: flex-end; gap: var(--oc-space-0-5); flex: none; padding-top: var(--oc-border); }
    .xr-w__meta .xr-age { margin-left: 0; padding-left: 0; }

    .xr-row--more { padding: var(--oc-space-1) var(--oc-space-2); }
  }
</style>
