<script lang="ts">
  import type { TaskManagerMessage } from './huddle-model';
  import { postBody } from './task-manager-posts';
  import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';

  let { message, text = undefined, cls = '', limit = 0, more = false }: { message: TaskManagerMessage; text?: string; cls?: string; limit?: number; more?: boolean } = $props();
</script>

<div class="hda {cls}" data-task-manager-answer={message.id}>
  {#if message.quote}<blockquote class="hda-quote" data-task-manager-answer-quote><TaskManagerMarkdown text={message.quote.text} inline /></blockquote>{/if}
  <div class="hda-body" data-task-manager-answer-body><TaskManagerMarkdown text={postBody(text ?? message.text)} {limit} {more} /></div>
</div>

<style>
  @layer components {
    .hda {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }

    .hda-quote {
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 3;
      line-clamp: 3;
      overflow: hidden;
      margin: 0;
      padding: 0 0 0 8px;
      border-left: 1px solid var(--_post, var(--oc-orange));
      color: var(--oc-text-muted);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .hda-body {
      min-width: 0;
      color: var(--oc-text-primary);
    }
  }
</style>
