
<script lang="ts">
  import { tick, untrack } from 'svelte';
  import type { CrosstalkThread } from '../../../lib/crosstalk/history/history-model';
  import { t } from '../../../lib/i18n/index.svelte';
  import Button from '../../../lib/base/Button.svelte';
  import State from '../../../lib/base/State.svelte';
  import type { ReadState } from '../../../lib/crosstalk/history/conversations.svelte';
  import { clockText, fullTime, transcript, type ThreadMessage } from './model';

  interface Props {
    thread: CrosstalkThread;
    messages: ThreadMessage[];
    readState: ReadState;
    reason: string;
    older: boolean;
    nowMs: number;
    width: number;
    takeFocus: boolean;
    wrap: boolean;
    reserveCorner: boolean;
    onolder: () => void;
  }

  let { thread, messages, readState, reason, older, nowMs, width, takeFocus, wrap, reserveCorner, onolder }: Props = $props();

  const LONG_CHARS = 480;
  const LONG_LINES = 8;

  let scroller = $state<HTMLDivElement | null>(null);
  let opened = $state<Record<string, boolean>>({});
  const items = $derived(transcript(messages, thread.participants, nowMs));
  const [a, b] = $derived(thread.participants);
  const indent = $derived(width >= 360);

  function about(side: CrosstalkThread['participants'][number] | undefined): string {
    if (!side) return '';
    return [side.name, side.project_name ? `${t('crosstalk.widget.about_project', { name: side.project_name })}` : '', [side.provider, side.model].filter(Boolean).join(' ')]
      .filter(Boolean).join(', ');
  }

  function long(text: string): boolean {
    return text.length > LONG_CHARS || text.split('\n').length > LONG_LINES;
  }

  $effect(() => {
    if (takeFocus && scroller) untrack(() => scroller?.focus({ preventScroll: true }));
  });

  let lastThread = '';
  let lastFirst = '';
  let lastHeight = 0;
  $effect.pre(() => {
    void messages;
    if (scroller) lastHeight = scroller.scrollHeight - scroller.scrollTop;
  });
  $effect(() => {
    const first = messages[0]?.id ?? '';
    const el = scroller;
    if (!el || readState !== 'ready') return;
    void tick().then(() => {
      if (thread.thread !== lastThread) el.scrollTop = el.scrollHeight;
      else if (first !== lastFirst) el.scrollTop = el.scrollHeight - lastHeight;
      else if (el.scrollHeight - el.scrollTop - el.clientHeight < 80) el.scrollTop = el.scrollHeight;
      lastThread = thread.thread;
      lastFirst = first;
    });
  });
</script>

<section class="xv" class:xv--wrap={wrap} class:xv--corner={reserveCorner} aria-label={t('crosstalk.widget.conversation_between', { a: a?.name ?? '', b: b?.name ?? '' })} data-crosstalk-thread={thread.thread}>
  <p class="xv-head">
    <bdi class="xv-side xv-side--a" title={about(a)}>{a?.name}</bdi>
    <span class="xv-and">{t('crosstalk.widget.and')}</span>
    <bdi class="xv-side xv-side--b" title={about(b)}>{b?.name}</bdi>
    <span class="xv-count">{t(thread.message_count === 1 ? 'crosstalk.widget.messages_one' : 'crosstalk.widget.messages_many', { n: thread.message_count })}</span>
  </p>
  
  <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
  <div class="xv-scroll" bind:this={scroller} tabindex="0" role="log" aria-live="polite">
    {#if older}
      <div class="xv-older"><Button data-crosstalk-older onclick={onolder}>{t('crosstalk.widget.older_messages')}</Button></div>
    {/if}
    {#if readState === 'failed'}
      <State kind="error" inline title={t('crosstalk.widget.thread_failed', { reason })} />
    {:else if readState === 'loading'}
      <State kind="loading" inline title={t('crosstalk.widget.thread_loading')} />
    {:else}
      {#each items as item (item.key)}
        {#if item.kind === 'day'}
          <p class="xv-day"><span>{item.label}</span></p>
        {:else if item.kind === 'notice'}
          <p class="xv-notice"><span class="xv-notice__tag">{t('crosstalk.widget.notice')}</span> {item.text}
            <time class="xv-time" datetime={new Date(item.at * 1000).toISOString()} title={fullTime(item.at)}>{clockText(item.at)}</time></p>
        {:else}
          {@const folded = long(item.message.text) && !opened[item.key]}
          <article class="xv-msg" class:xv-msg--b={item.side === 1} class:xv-msg--indent={item.side === 1 && indent}
            class:xv-msg--run={!item.head} data-message-id={item.message.id}>
            {#if item.head}
              <header class="xv-msg__head">
                <bdi class="xv-from">{item.from}</bdi><span class="xv-arrow" aria-label={t('crosstalk.widget.wrote_to')}>→</span><bdi class="xv-to">{item.to}</bdi>
                <time class="xv-time" datetime={new Date(item.message.created_at * 1000).toISOString()} title={fullTime(item.message.created_at)}>{clockText(item.message.created_at)}</time>
              </header>
            {/if}
            {#if item.replyTo}<p class="xv-reply" title={item.replyTo}>{t('crosstalk.widget.answers', { quote: item.replyTo })}</p>{/if}
            <p class="xv-text" class:xv-text--folded={folded}>{item.message.text}</p>
            {#if long(item.message.text)}
              <Button variant="quiet" size="sm" aria-expanded={!folded}
                onclick={() => (opened = { ...opened, [item.key]: folded })}>{t(folded ? 'crosstalk.widget.show_all' : 'crosstalk.widget.show_less')}</Button>
            {/if}
            {#if item.asksReply || item.delivery}
              <p class="xv-facts">
                {#if item.asksReply}<span class="xv-ask">{t('crosstalk.widget.asked_reply')}</span>{/if}
                {#if item.delivery}<span class="xv-trouble" class:xv-trouble--bad={item.delivery.bad} title={item.message.reason ?? ''}>{item.delivery.word}</span>{/if}
              </p>
            {/if}
          </article>
        {/if}
      {/each}
    {/if}
  </div>
</section>

<style>
  @layer components {
    .xv { display: flex; flex-direction: column; flex: 1 1 auto; min-width: 0; min-height: 0; }
    .xv-head { display: flex; align-items: baseline; gap: var(--oc-space-1-5); flex: none; height: 22px; margin: 0; padding: 0 var(--oc-space-2); line-height: 22px; background: var(--oc-ground-titlerow); box-shadow: inset 0 -1px 0 var(--oc-line-panel); white-space: nowrap; overflow: hidden; font-size: var(--oc-fs-label); }
    .xv-side { min-width: 2ch; max-width: 40%; overflow: hidden; text-overflow: ellipsis; color: var(--oc-text-primary); }
    .xv-and { flex: none; color: var(--oc-text-dim); }
    .xv-count { flex: none; margin-left: auto; color: var(--oc-text-dim); }

    .xv-scroll { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: var(--oc-space-1) var(--oc-space-2) var(--oc-space-2); border: 1px solid transparent; }
    .xv-older { display: flex; justify-content: center; margin-bottom: var(--oc-space-1); }

    .xv-day { display: flex; align-items: center; gap: var(--oc-space-2); margin: var(--oc-space-2) 0 var(--oc-space-1); color: var(--oc-text-dim); font-size: var(--oc-fs-label); letter-spacing: 0.08em; text-transform: uppercase; }
    .xv-day::before, .xv-day::after { content: ''; flex: 1 1 auto; height: 1px; background: var(--oc-line-panel); }

    .xv-notice { margin: var(--oc-space-1) 0; padding-left: calc(var(--oc-space-2) + var(--oc-space-0-5)); color: var(--oc-text-dim); font-size: var(--oc-fs-label); }
    .xv-notice__tag { text-transform: uppercase; letter-spacing: 0.08em; }

    .xv-msg { margin-top: var(--oc-space-2); padding-left: var(--oc-space-2); box-shadow: inset 2px 0 0 var(--oc-text-secondary); }
    .xv-msg--b { box-shadow: inset 2px 0 0 var(--oc-line-rule, var(--oc-line-panel)); }
    .xv-msg--indent { margin-left: var(--oc-space-3, var(--oc-space-3)); }
    .xv-msg--run { margin-top: var(--oc-space-0-5); }
    .xv-msg__head { display: flex; align-items: baseline; gap: var(--oc-space-1-5); min-width: 0; white-space: nowrap; font-size: var(--oc-fs-label); }
    .xv-from { min-width: 2ch; overflow: hidden; text-overflow: ellipsis; color: var(--oc-text-primary); }
    .xv-to { min-width: 2ch; overflow: hidden; text-overflow: ellipsis; color: var(--oc-text-secondary); }
    .xv-arrow { flex: none; color: var(--oc-text-dim); }
    .xv-time { flex: none; margin-left: auto; padding-left: var(--oc-space-1); color: var(--oc-text-dim); font-size: var(--oc-fs-label); }
    .xv-notice .xv-time { margin-left: var(--oc-space-1); }

    .xv-reply { margin: var(--oc-space-0-5) 0 0; overflow: hidden; color: var(--oc-text-dim); font-size: var(--oc-fs-label); white-space: nowrap; text-overflow: ellipsis; }
    .xv-text { margin: var(--oc-space-0-5) 0 0; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--oc-text-primary); }
    .xv-text--folded { display: -webkit-box; -webkit-line-clamp: 8; line-clamp: 8; -webkit-box-orient: vertical; overflow: hidden; }

    .xv-facts { display: flex; flex-wrap: wrap; gap: var(--oc-space-2); margin: var(--oc-space-0-5) 0 0; font-size: var(--oc-fs-label); }
    .xv-ask { color: var(--oc-yellow); }
    .xv-trouble { color: var(--oc-yellow); }
    .xv-trouble--bad { color: var(--oc-coral); }

    .xv--wrap .xv-head { flex-wrap: wrap; height: auto; min-height: 22px; white-space: normal; }
    .xv--wrap .xv-side { max-width: none; overflow: visible; overflow-wrap: anywhere; }
    .xv--wrap .xv-msg__head { flex-wrap: wrap; white-space: normal; }
    .xv--wrap .xv-from, .xv--wrap .xv-to { overflow: visible; overflow-wrap: anywhere; }
    .xv--corner .xv-head { padding-right: calc(var(--oc-space-5) + var(--oc-space-1-5)); }
  }
</style>
