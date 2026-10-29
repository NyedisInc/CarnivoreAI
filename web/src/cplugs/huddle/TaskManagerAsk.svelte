<script lang="ts">
  import type { TaskManagerMessage } from './huddle-model';
  import { askFold, askLead, askParts, isFormAsk, postBody } from './task-manager-posts';
  import TaskManagerAskBubble from './ask/TaskManagerAskBubble.svelte';
  import TaskManagerAskForm from './ask/TaskManagerAskForm.svelte';
  import TaskManagerAskInline from './ask/TaskManagerAskInline.svelte';
  import { inlineQuestion } from './ask/ask-model';
  import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';
  import { mdPlain } from './task-manager-markdown';
  import { truncatedTip } from '../sdk';

  let { message, cls = '', folded = false, oneLine = false }: { message: TaskManagerMessage; cls?: string; folded?: boolean; oneLine?: boolean } = $props();
  const parts = $derived(askParts(message));
  const fold = $derived(folded ? askFold(message, oneLine) : null);
  const folding = $derived(fold !== null && fold.foldable);
  const limit = $derived(fold && fold.foldable ? fold.limit : 0);
  const more = $derived(fold !== null && fold.foldable && fold.more);
  const context = $derived(fold && fold.foldable ? fold.context : (parts?.context ?? ''));
  const form = $derived(isFormAsk(message));
  const inline = $derived(form && inlineQuestion(message.form) !== null);
  const lead = $derived(askLead(message));
  const shown = $derived(fold && fold.foldable && parts ? parts.questions.slice(0, fold.shown) : (parts?.questions ?? []));
</script>

{#if parts}
  <div class="tkm-ask {cls}" data-task-manager-ask={message.id}>
    {#if inline}
      <TaskManagerAskInline {message} compact={folded} />
    {:else if form && folded}
      
      {#if lead}<div class="tkm-ask-lead" data-task-manager-ask-lead use:truncatedTip={mdPlain(lead)}><TaskManagerMarkdown text={lead} inline /></div>{/if}
      <TaskManagerAskBubble {message} />
    {:else if form && oneLine && !message.answered && !folded}
      
      {#if parts.context}<div class="tkm-ask-context" data-task-manager-ask-context><TaskManagerMarkdown text={postBody(parts.context)} /></div>{/if}
      <TaskManagerAskBubble {message} />
    {:else if form && !message.answered}
      
      <TaskManagerAskForm messageId={message.id} mode="inline" />
    {:else}
      {#if context}<div class="tkm-ask-context" data-task-manager-ask-context><TaskManagerMarkdown text={postBody(context)} {limit} {more} /></div>{/if}
      {#if form}<TaskManagerAskBubble {message} />{:else}
      <ol class="tkm-ask-list" data-task-manager-ask-list>
        {#each shown as question, at (at)}<li class="tkm-ask-q"><TaskManagerMarkdown text={postBody(question)} inline /></li>{/each}
      </ol>
      {/if}
    {/if}
  </div>
{:else}
  <span class={cls} use:truncatedTip={mdPlain(message.text)}><TaskManagerMarkdown text={postBody(fold && folding ? fold.text : message.text)} {limit} {more} /></span>
{/if}

<style>
  @layer components {
    .tkm-ask {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }

    .tkm-ask-lead {
      overflow: hidden;
      color: var(--oc-text-primary);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .tkm-ask-context {
      color: var(--oc-text-secondary);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .tkm-ask-list {
      display: flex;
      flex-direction: column;
      gap: 2px;
      margin: 0;
      padding: 0 0 0 20px;
      color: var(--oc-text-primary);
      overflow-wrap: anywhere;
    }

    .tkm-ask-q::marker {
      color: var(--oc-yellow-bright);
      font-variant-numeric: tabular-nums;
    }
  }
</style>
