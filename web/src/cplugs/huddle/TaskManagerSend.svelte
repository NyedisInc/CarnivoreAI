<script lang="ts">
  import { Icon } from '../sdk/ui';
  import { t } from '../sdk';
  import { huddle } from './huddle.svelte';
  import { FOOTER_ICON_PX } from './task-manager-footer';
  import { viewKey } from './task-manager-view';
  import { flushQueued, listsToSend, pickFor, sendLists, sendPicks, waitingToSend } from './huddle-send-many.svelte';
  import { fillProgress, queuedKeys, queueSummary, startSendQueue, sendQueue } from './task-manager-send-queue.svelte';
  import TaskManagerTargetPick from './TaskManagerTargetPick.svelte';
  import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';

  let { compose = null }: { compose?: { text: string; add: () => Promise<void> } | null } = $props();

  const view = viewKey();
  let busy = $state(false);
  const composing = $derived(!!compose && compose.text.trim() !== '');
  const waiting = $derived(waitingToSend(view(), huddle.lists));
  const queued = $derived(queueSummary(sendQueue.state, view()));
  const fill = $derived(queued ? fillProgress(queued, Date.now(), sendQueue.skewMs) : null);
  const shown = $derived(queued ? queued.count : waiting);
  const words = $derived(composing ? t('cplug.huddle.send.send') : queued ? t('cplug.huddle.send.queued', { count: queued.count })
    : waiting > 0 ? t('cplug.huddle.send.waiting', { count: waiting }) : t('cplug.huddle.send.nothing'));
  $effect(() => { startSendQueue(); });
  let chosen = $state<Record<string, string>>({});
  const asking = $derived(sendPicks.asking);
  const ready = $derived((asking ?? []).filter((a) => chosen[a.list]).map((a) => a.list));

  $effect(() => {
    if (asking) chosen = Object.fromEntries(asking.filter((a) => sendPicks.picks[a.list]).map((a) => [a.list, sendPicks.picks[a.list] as string]));
  });

  async function press(): Promise<void> {
    if (busy || (waiting === 0 && !queued && !composing)) return;
    busy = true;
    if (composing && compose) {
      await compose.add();
      busy = false;
      return;
    }
    if (queued) await flushQueued(queuedKeys(sendQueue.state, view()));
    else await sendLists(listsToSend(view(), huddle.lists));
    busy = false;
  }

  async function send(): Promise<void> {
    const lists = ready;
    if (!lists.length || busy) return;
    for (const list of lists) pickFor(list, chosen[list] ?? null);
    sendPicks.asking = null;
    busy = true;
    await sendLists(lists);
    busy = false;
  }

  function close(): void {
    sendPicks.asking = null;
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.stopPropagation();
      close();
    }
  }
</script>

<span class="hdtl">
  <button type="button" class="oc-ibtn oc-ibtn--bare hd-key hd-key--act hdtl-key" data-task-manager-send data-task-manager-send-count={waiting}
          data-task-manager-send-queued={queued ? queued.count : 0}
          aria-label={words} title={words}
          aria-haspopup="dialog" aria-expanded={asking !== null}
          disabled={busy || (waiting === 0 && !queued && !composing)} onclick={() => void press()}>{#if queued && fill}<span class="hdtl-fillbox" aria-hidden="true">{#key queued.resetAt}<span class="hdtl-fill" data-task-manager-send-fill data-task-manager-send-fill-from={queued.resetAt} data-task-manager-send-fill-due={queued.dueAt}
              style:--hdtl-dur="{fill.durationS}s" style:--hdtl-delay="-{fill.elapsedS}s" style:--hdtl-p={fill.fraction}></span>{/key}</span>{/if}<Icon name="send" size={FOOTER_ICON_PX} />{#if shown > 0}<span class="hdtl-count" data-task-manager-send-badge>{shown}</span>{/if}</button>
  {#if asking}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div class="hdtl-pick" role="dialog" aria-label={t('cplug.huddle.send.ask_title')} tabindex="-1" onkeydown={onKeydown} data-task-manager-send-ask>
      <p class="hdtl-pick-title">{t('cplug.huddle.send.ask_title')}</p>
      <p class="hdtl-why">{t('cplug.huddle.send.ask_why')}</p>
      <ul class="hdtl-asks">
        {#each asking as ask (ask.list)}
          <li class="hdtl-ask" data-task-manager-send-ask-list={ask.list}>
            <span class="hdtl-ask-name">{ask.name}</span>
            {#if ask.items.length}
              <ul class="hdtl-ask-items">
                {#each ask.items.slice(0, 4) as entry (entry.id)}<li class="hdtl-ask-item"><TaskManagerMarkdown text={entry.text} inline /></li>{/each}
                {#if ask.items.length > 4}<li class="hdtl-ask-more">{t('cplug.huddle.send.ask_more', { count: ask.items.length - 4 })}</li>{/if}
              </ul>
            {/if}
            {#if !ask.sessions.length}
              <span class="hdtl-why" data-task-manager-send-ask-none={ask.list}>{t('cplug.huddle.send.none')}</span>
            {/if}
            <TaskManagerTargetPick list={ask.list} sessions={ask.sessions} value={chosen[ask.list] ?? ''} cls="hdtl-ask-pick"
                              label={t('cplug.huddle.send.ask_pick', { name: ask.name })} data-task-manager-send-ask-pick={ask.list}
                              onPick={(v) => { chosen = { ...chosen, [ask.list]: v }; }} />
          </li>
        {/each}
      </ul>
      <div class="hdtl-foot">
        <button type="button" class="oc-btn oc-btn--sm" onclick={close}>{t('cplug.huddle.send.cancel')}</button>
        <button type="button" class="oc-btn oc-btn--sm oc-btn--confirm" data-task-manager-send-send disabled={!ready.length || busy}
                onclick={() => void send()}>{t('cplug.huddle.send.send')}</button>
      </div>
    </div>
  {/if}
</span>

<style>
  @layer components {
    .hdtl {
      position: relative;
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      min-width: 0;
    }

    .hdtl-key {
      isolation: isolate;
    }

    .hdtl-fillbox {
      position: absolute;
      inset: 0;
      z-index: -1;
      overflow: hidden;
      pointer-events: none;
    }

    .hdtl-fill {
      position: absolute;
      inset: 0;
      background: color-mix(in srgb, var(--oc-orange) 45%, transparent);
      transform: scaleX(var(--hdtl-p, 0));
      transform-origin: left center;
      animation: hdtl-fill var(--hdtl-dur, 8s) linear var(--hdtl-delay, 0s) both;
    }

    @keyframes hdtl-fill {
      from { transform: scaleX(0); }
      to { transform: scaleX(1); }
    }

    @media (prefers-reduced-motion: reduce) {
      .hdtl-fill {
        animation: none;
      }
    }

    .hdtl-count {
      position: absolute;
      top: -0.4em;
      right: -0.4em;
      min-width: 1.4em;
      padding: 0 0.3em;
      box-sizing: border-box;
      border: 1px solid var(--oc-orange);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-raised);
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      line-height: 1.4;
      text-align: center;
    }

    .hdtl-pick {
      position: absolute;
      bottom: calc(100% + 4px);
      right: 0;
      z-index: 20;
      width: 240px;
      padding: var(--oc-space-2);
      border: 1px solid var(--oc-line-frame);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-raised);
      box-shadow: var(--oc-shadow-lift);
    }

    .hdtl-pick-title {
      margin: 0 0 var(--oc-space-1);
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }



    .hdtl-why {
      margin: 0 0 var(--oc-space-2);
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
    }

    .hdtl-asks {
      display: flex;
      flex-direction: column;
      max-height: 260px;
      margin: 0;
      padding: 0;
      overflow-y: auto;
      list-style: none;
    }

    .hdtl-ask {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 6px 0;
      box-shadow: inset 0 1px 0 var(--oc-line-faint);
    }

    .hdtl-ask-name {
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hdtl-ask-items {
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .hdtl-ask-item,
    .hdtl-ask-more {
      overflow: hidden;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-micro);
      line-height: 16px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hdtl-ask-more {
      color: var(--oc-text-muted);
    }

    .hdtl-ask :global(.hdtl-ask-pick) {
      width: 100%;
    }

    .hdtl-ask .hdtl-why {
      margin: 0;
    }


    .hdtl-foot {
      display: flex;
      justify-content: flex-end;
      gap: var(--oc-space-1);
      margin-top: var(--oc-space-2);
    }
  }
</style>
