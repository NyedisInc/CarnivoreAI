<script lang="ts">
  import { tick } from 'svelte';
  import { t } from '../sdk';
  import { isSystemLine, messageTime, type HuddleItem } from './huddle-model';
  import { bubbleKindOf } from './task-manager-bubbles';
  import TaskManagerBubble from './TaskManagerBubble.svelte';
  import TaskManagerAnswerBox from './TaskManagerAnswerBox.svelte';
  import TaskManagerArtifactCard from './TaskManagerArtifactCard.svelte';
  import TaskManagerRoundCard from './TaskManagerRoundCard.svelte';
  import TaskManagerAsk from './TaskManagerAsk.svelte';
  import TaskManagerFormAnswer from './TaskManagerFormAnswer.svelte';
  import { Icon } from '../sdk/ui';
  import TaskManagerFiles from './TaskManagerFiles.svelte';
  import HuddleReply from './HuddleReply.svelte';
  import CrosstalkTrail from './CrosstalkTrail.svelte';
  import TaskManagerScheduleOffer from './TaskManagerScheduleOffer.svelte';
  import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';
  import { shownAuthor } from './task-manager-author';

  let { item, agentName = '', closed = false, noSend = false, firstBubble = false, conversation = true, skip = null }: { item: HuddleItem; agentName?: string; closed?: boolean; noSend?: boolean; firstBubble?: boolean; conversation?: boolean; skip?: number | null } = $props();
  const firstBy = $derived(shownAuthor(item));

  let box = $state<HTMLElement | null>(null);
  const newest = $derived(item.thread.at(-1)?.id ?? null);

  $effect(() => {
    void newest;
    if (box && pinned) void tick().then(() => scrollToNewest(box));
  });

  let pinned = true;

  const PIN_SLACK_PX = 24;

  function trackPinned(): void {
    if (box) pinned = box.scrollHeight - box.scrollTop - box.clientHeight <= PIN_SLACK_PX;
  }

  function scrollToNewest(el: HTMLElement | null): void {
    if (el) el.scrollTop = el.scrollHeight;
  }
</script>

<div class="hdt" data-task-manager-thread={item.id}>
  {#if conversation && (item.thread.length > 0 || (firstBubble && item.text))}
    <div class="hdt-box" bind:this={box} onscroll={trackPinned} data-task-manager-thread-box={item.id} data-task-manager-thread-newest={newest ?? undefined}>
      <ol class="hdt-list" aria-label={t('cplug.huddle.thread.label')}>
        {#if firstBubble && item.text}
          
          <TaskManagerBubble kind={firstBy === 'claude' ? 'claude' : 'owner'} tag="li" layout="thread" author={firstBy}
                        cls="hdt-msg {firstBy === 'claude' ? 'hdt-msg--claude' : 'hdt-msg--joe'}"
                        data-task-manager-first={item.id} data-by={firstBy}>
            {#snippet body()}<div class="hb-body hdt-text" data-task-manager-description={item.id}><TaskManagerMarkdown text={item.text} /></div>{/snippet}
          </TaskManagerBubble>
        {/if}
        {#each skip === null ? item.thread : item.thread.filter((m) => m.id !== skip) as message (message.id)}
          {#if isSystemLine(message)}
            
            <li class="hdt-nudge" data-task-manager-nudge-line={message.id} data-task-manager-system-line={message.category}>{message.text}, {messageTime(message.created_at)}</li>
          {:else}
          {@const formAnswer = bubbleKindOf(message) === 'form_answer'}
          <TaskManagerBubble kind={bubbleKindOf(message)} tag="li" layout="thread" author={formAnswer ? null : message.author} time={message.created_at}
                        cls="hdt-msg {formAnswer ? 'hdt-msg--form' : message.author === 'claude' ? 'hdt-msg--claude' : 'hdt-msg--joe'}"
                        waiting={message.kind === 'question' && !message.answered}
                        data-task-manager-message={message.id} data-kind={message.kind} data-by={message.author}>
            {#snippet head()}{#if formAnswer}<span class="hb-fa-icon" aria-hidden="true"><Icon name="list" size={12} strokeWidth={1.75} /></span>{/if}{/snippet}
            {#snippet body()}
              {#if formAnswer}<div class="hb-body hdt-text"><TaskManagerFormAnswer {message} /></div>{:else if message.kind === 'answer'}<div class="hb-body hdt-text"><TaskManagerAnswerBox {message} /></div>{:else if message.artifact}<div class="hb-body hdt-text"><TaskManagerArtifactCard itemId={item.id} artifact={message.artifact} /></div>{:else if message.board_round}<div class="hb-body hdt-text"><TaskManagerRoundCard round={message.board_round} text={message.text} /></div>{:else if message.text || !message.files?.length}<div class="hb-body hdt-text"><TaskManagerAsk {message} /></div>{/if}
            {/snippet}
            {#snippet after()}{#if message.files?.length}<TaskManagerFiles itemId={item.id} files={message.files} />{/if}{#if message.schedule}<TaskManagerScheduleOffer {item} {message} />{/if}{/snippet}
          </TaskManagerBubble>
          {/if}
        {/each}
      </ol>
    </div>
  {/if}
  {#if firstBubble}<CrosstalkTrail {item} />{/if}
  {#if !closed}<div class="hdt-reply"><HuddleReply {item} {agentName} {noSend} /></div>{/if}
</div>

<style>
  @layer components {
    .hdt {
      display: flex;
      flex-direction: column;
      gap: 12px;
      min-width: 0;
    }

    .hdt-nudge {
      list-style: none;
      color: var(--oc-text-dim);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.04em;
    }

    .hdt-reply {
      min-width: 0;
      margin-left: calc(-1 * var(--hdr-lead, 0px));
    }

    .hdt-box {
      max-height: var(--hdt-max, 320px);
      margin-left: calc(-1 * var(--hdr-lead, 0px));
      padding: 8px;
      overflow-y: auto;
      overscroll-behavior: contain;
      border: 1px solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm, 2px);
      background: var(--oc-ground-page);
    }

    .hdt-list {
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin: 0;
      padding: 0;
    }

    .hdt-list > :global(.hdt-msg) {
      max-width: 88%;
    }

    .hdt-list > :global(.hdt-msg--claude) {
      align-self: flex-start;
    }

    .hdt-list > :global(.hdt-msg--joe) {
      align-self: flex-end;
    }

    .hdt-list > :global(.hdt-msg--form) {
      align-self: stretch;
      max-width: none;
      margin-inline: var(--hdt-form-inset, 24px);
    }

    .hdt-list :global(.hdt-text) {
      white-space: normal;
    }
  }
</style>
