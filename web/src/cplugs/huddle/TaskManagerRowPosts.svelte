<script lang="ts">
  import { Icon } from '../sdk/ui';
  import { t } from '../sdk';
  import type { HuddleItem, TaskManagerMessage } from './huddle-model';
  import { POST_KINDS, QUESTION_BLOCK, askFold, isFoldToggle, isFormAsk, isShiftDismiss, openQuestions, postBody, postFold, postKindOf, rowFeed, rowQuestionPick, unreadPosts, type TaskManagerPostKind } from './task-manager-posts';
  import { bubbleKindOf } from './task-manager-bubbles';
  import TaskManagerBubble from './TaskManagerBubble.svelte';
  import type { RowParts } from './huddle-density';
  import { readPost } from './huddle.svelte';
  import { cancelMiddleScroll, onMiddleDismiss } from './task-manager-middle-dismiss';
  import { createCloseCue } from './task-manager-close-cue.svelte';
  import TaskManagerAnswerBox from './TaskManagerAnswerBox.svelte';
  import TaskManagerArtifactCard from './TaskManagerArtifactCard.svelte';
  import TaskManagerAsk from './TaskManagerAsk.svelte';
  import { dismissAsk } from './ask/ask-host';
  import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';
  import TaskManagerFiles from './TaskManagerFiles.svelte';
  import HuddleReply from './HuddleReply.svelte';

  let { item, parts, only = null, unfolded = false, oneLine = false }: { item: HuddleItem; parts: RowParts; only?: number | null; unfolded?: boolean; oneLine?: boolean } = $props();

  const feed = $derived(only === null ? rowFeed(item) : rowFeed(item).filter((message) => message.id === only));
  const pick = $derived(rowQuestionPick(feed));
  const hasPosts = $derived(unreadPosts(item).length > 0);
  const questionCount = $derived(parts.questions ? openQuestions(item).length : 0);
  let opened = $state<Record<number, boolean>>({});

  function onPostClick(event: MouseEvent, message: TaskManagerMessage): void {
    if (!isShiftDismiss(event)) return onFoldClick(event, message.id, message.kind !== 'question' && postFold(message.text, oneLine).foldable);
    event.preventDefault();
    void readPost(item, message);
  }

  const canDismissAsk = (message: TaskManagerMessage): boolean => message.kind === 'question' && isFormAsk(message) && !message.answered;

  function dismissQuestion(event: MouseEvent, message: TaskManagerMessage): void {
    event.preventDefault();
    event.stopPropagation();
    if (canDismissAsk(message)) void dismissAsk(message.id);
  }

  function onQuestionClick(event: MouseEvent, message: TaskManagerMessage, foldable: boolean): void {
    if (canDismissAsk(message) && isShiftDismiss(event)) return dismissQuestion(event, message);
    onFoldClick(event, message.id, foldable);
  }

  function onFoldClick(event: MouseEvent, id: number, foldable: boolean): void {
    const selected = typeof window.getSelection === 'function' ? (window.getSelection()?.toString() ?? '') : '';
    if (foldable && isFoldToggle(event, selected)) opened[id] = opened[id] !== true;
  }

  function onPostDown(event: MouseEvent): void {
    if (isShiftDismiss(event)) event.preventDefault();
    cancelMiddleScroll(event);
  }

  const cue = createCloseCue();
  $effect(() => cue.attach());

  let iconOver = $state<number | null>(null);
  const armed = (id: number): boolean => cue.active === id || iconOver === id;

  const isPost = (message: TaskManagerMessage): boolean => postKindOf(message) !== null;
</script>


{#snippet foldKey(id: number, foldable: boolean, open: boolean)}
  {#if foldable}
    <button type="button" class="tkm-post-fold" aria-expanded={open} data-task-manager-post-fold={id}
            aria-label={t(open ? 'cplug.huddle.post.fold' : 'cplug.huddle.post.unfold')} title={t(open ? 'cplug.huddle.post.fold' : 'cplug.huddle.post.unfold')}
            onclick={() => { opened[id] = !open; }}><Icon name={open ? 'chevron-up' : 'chevron-down'} size={12} strokeWidth={1.75} /></button>
  {/if}
{/snippet}

{#snippet files(message: TaskManagerMessage)}
  {#if message.artifact}<div class="tkm-post-files"><TaskManagerArtifactCard itemId={item.id} artifact={message.artifact} /></div>{/if}
  {#if message.files?.length}<div class="tkm-post-files"><TaskManagerFiles itemId={item.id} files={message.files} /></div>{/if}
{/snippet}

{#if feed.length}
  <ul class="tkm-posts" aria-label={t('cplug.huddle.feed.block')} data-task-manager-feed={item.id}
      data-task-manager-posts={hasPosts ? item.id : undefined} data-task-manager-questions={questionCount ? item.id : undefined}>
    {#each feed as message (message.id)}
      {#if message.kind === 'question' && message.id !== pick.shown}
        
      {:else if message.kind === 'question'}
        {@const fold = askFold(message, oneLine)}
        {@const open = unfolded || opened[message.id] === true}
        {@const closable = canDismissAsk(message)}
        <TaskManagerBubble kind="question" tag="li" cls="tkm-posts-post {closable && armed(message.id) ? 'tkm-posts-post--closing' : ''}" data-task-manager-post={message.id} data-task-manager-post-kind="question"
                      data-task-manager-post-folded={fold.foldable ? String(!open) : undefined} title={closable ? t('cplug.huddle.question.shift_hint') : undefined}
                      onmousedown={closable ? onPostDown : undefined} onclick={(event: MouseEvent) => onQuestionClick(event, message, fold.foldable)}
                      onpointerover={closable ? (event: PointerEvent) => cue.point(message.id, event) : undefined}
                      onpointermove={closable ? (event: PointerEvent) => cue.point(message.id, event) : undefined}
                      onpointerleave={closable ? () => cue.leave(message.id) : undefined}>
          {#snippet lead()}
            {#if closable}
              <button type="button" class="tkm-post-read" aria-label={t('cplug.huddle.question.dismiss')}
                      data-task-manager-question-dismiss={message.id} onclick={(event: MouseEvent) => dismissQuestion(event, message)}
                      onpointerenter={() => { iconOver = message.id; }} onpointerleave={() => { iconOver = null; }} onfocus={() => { iconOver = message.id; }} onblur={() => { iconOver = null; }}><Icon name={armed(message.id) ? 'close' : QUESTION_BLOCK.icon} size={12} strokeWidth={1.75} /></button>
            {:else}<span class="tkm-post-read tkm-post-mark"><Icon name={QUESTION_BLOCK.icon} size={12} strokeWidth={1.75} /></span>{/if}
          {/snippet}
          {#snippet body()}<TaskManagerAsk {message} cls="tkm-post-text{oneLine && fold.foldable && !open ? ' tkm-post-text--one' : ''}" folded={!open} oneLine={oneLine} />{/snippet}
          {#snippet after()}
            {@render foldKey(message.id, fold.foldable, open)}
            {#if closable && armed(message.id)}<span class="tkm-post-close" data-task-manager-post-close={message.id} aria-hidden="true">{t('cplug.huddle.post.close_cue')}</span>{/if}
            {@render files(message)}
          {/snippet}
        </TaskManagerBubble>
        {#if pick.hidden > 0}<li class="tkm-posts-more" data-task-manager-more-open={pick.hidden}>{t('cplug.huddle.row.more_open', { n: pick.hidden })}</li>{/if}
      {:else if isPost(message)}
        {@const meta = POST_KINDS[postKindOf(message) as TaskManagerPostKind]}
        {@const fold = postFold(message.text)}
        {@const open = unfolded || opened[message.id] === true}
        {@const cut = fold.foldable && !open}
        <TaskManagerBubble kind={bubbleKindOf(message)} tag="li" cls="tkm-posts-post {armed(message.id) ? 'tkm-posts-post--closing' : ''}"
                      data-task-manager-post={message.id} data-task-manager-post-kind={message.kind} data-task-manager-post-folded={fold.foldable ? String(!open) : undefined}
                      title={t('cplug.huddle.post.shift_hint')} onmousedown={onPostDown} onauxclick={(event: MouseEvent) => onMiddleDismiss(event, () => void readPost(item, message))} onclick={(event: MouseEvent) => onPostClick(event, message)}
                      onpointerover={(event: PointerEvent) => cue.point(message.id, event)} onpointermove={(event: PointerEvent) => cue.point(message.id, event)}
                      onpointerleave={() => cue.leave(message.id)}>
          {#snippet lead()}
            <button type="button" class="tkm-post-read" aria-label={t(meta.readKey)} title={t(meta.readKey)}
                    data-task-manager-post-read={message.id} onclick={() => void readPost(item, message)}
                    onpointerenter={() => { iconOver = message.id; }} onpointerleave={() => { iconOver = null; }} onfocus={() => { iconOver = message.id; }} onblur={() => { iconOver = null; }}><Icon name={armed(message.id) ? 'close' : meta.icon} size={12} strokeWidth={1.75} /></button>
          {/snippet}
          {#snippet body()}
            <span class="hb-body tkm-post-text" class:tkm-post-text--lead={cut && fold.lead} class:tkm-post-text--one={cut && oneLine}>{#if message.kind === 'answer'}<TaskManagerAnswerBox {message} text={cut ? fold.folded : fold.full} limit={cut ? fold.limit : 0} more={cut && fold.more} />{:else}<TaskManagerMarkdown text={postBody(cut ? fold.folded : fold.full)} limit={cut ? fold.limit : 0} more={cut && fold.more} />{/if}</span>
          {/snippet}
          {#snippet after()}
            {@render foldKey(message.id, fold.foldable, open)}
            {#if armed(message.id)}<span class="tkm-post-close" data-task-manager-post-close={message.id} aria-hidden="true">{t('cplug.huddle.post.close_cue')}</span>{/if}
            {@render files(message)}
          {/snippet}
        </TaskManagerBubble>
      {/if}
    {/each}
  </ul>
  {#if questionCount && parts.reply}<div class="tkm-question-reply" data-task-manager-question-reply={item.id}><HuddleReply {item} onRow /></div>{/if}
{/if}

<style>
  @layer components {
    .tkm-posts {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
      margin: 0 0 0 calc(-1 * var(--hdr-lead, 0px));
      padding: 0;
      list-style: none;
    }

    :global(.tkm-post-read) {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 14px;
      height: 18px;
      padding: 0;
      border: 1px solid transparent;
      border-radius: var(--oc-radius-sm);
      background: none;
      color: var(--_post);
      cursor: pointer;
    }

    .tkm-post-files {
      grid-column: 2 / -1;
      min-width: 0;
    }

    .tkm-posts-more {
      color: var(--oc-text-muted);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
    }

    .tkm-question-reply {
      min-width: 0;
      margin-left: calc(-1 * var(--hdr-lead, 0px));
    }

    .tkm-post-mark {
      cursor: default;
    }

    .tkm-post-fold {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      padding: 0;
      border: 1px solid transparent;
      border-radius: var(--oc-radius-sm);
      background: none;
      color: var(--oc-text-secondary);
      cursor: pointer;
    }

    .tkm-post-fold {
      color: var(--oc-text-muted);
    }

    .tkm-post-fold:hover {
      color: var(--oc-text-primary);
    }

    .tkm-posts > :global(.tkm-posts-post[data-task-manager-post-folded]) {
      cursor: pointer;
    }

    .tkm-posts > :global(.tkm-posts-post[data-task-manager-post-folded="true"]:hover) {
      background: color-mix(in srgb, var(--_post) 14%, transparent);
    }

    .tkm-posts > :global(.tkm-posts-post[data-task-manager-post-folded="true"]:hover .tkm-post-fold) {
      color: var(--oc-text-primary);
    }

    .tkm-posts > :global(.tkm-posts-post.tkm-posts-post--closing[data-task-manager-post]) {
      cursor: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' viewBox='0 0 24 24' fill='none' stroke-linecap='round'%3E%3Cg stroke='%23000' stroke-width='3.5' opacity='.6'%3E%3Ccircle cx='12' cy='12' r='8.5'/%3E%3Cpath d='M9 9l6 6m0-6l-6 6'/%3E%3C/g%3E%3Cg stroke='%23fff' stroke-width='1.5'%3E%3Ccircle cx='12' cy='12' r='8.5'/%3E%3Cpath d='M9 9l6 6m0-6l-6 6'/%3E%3C/g%3E%3C/svg%3E") 12 12, not-allowed;
    }

    :global(.tkm-post-read:hover) {
      color: var(--_post-hover);
    }

    .tkm-post-text {
      min-width: 0;
      color: var(--oc-text-primary);
      font-size: var(--hd-fs-body, var(--oc-fs-body));
      line-height: 1.5;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    :global(.tkm-post-close) {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: var(--oc-radius-sm);
      background: color-mix(in srgb, var(--oc-ground-panel) 70%, transparent);
      color: var(--oc-text-primary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.12em;
      text-transform: lowercase;
      pointer-events: none;
      animation: tkm-post-close-in 100ms ease-out;
    }

    @keyframes tkm-post-close-in {
      from { opacity: 0; }
      to { opacity: 1; }
    }

    @media (prefers-reduced-motion: reduce) {
      :global(.tkm-post-close) { animation: none; }
    }

    .tkm-post-text--lead {
      font-weight: 600;
    }

    .tkm-post-text--one,
    .tkm-post-text--one :global(p) {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
</style>
