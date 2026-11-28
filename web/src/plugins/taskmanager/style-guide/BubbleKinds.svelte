<script lang="ts">
  import TaskManagerBubble from '../TaskManagerBubble.svelte';
  import { BUBBLE_KINDS, type BubbleKind } from '../task-manager-bubbles';

  const at = Math.floor(Date.now() / 1000) - 240;
  const text = 'a **bold** claim, some *italic*, `code`, and a long tail that keeps going so the cut at the end of a folded line has something to cut';
  const author = (kind: BubbleKind): string => (kind === 'owner' ? 'joe' : 'claude');
</script>

<div class="sg-specimen__stack" style="display: flex; flex-direction: column; gap: 8px">
  {#each BUBBLE_KINDS as kind (kind)}
    <code>{kind}</code>
    <TaskManagerBubble {kind} layout="thread" author={author(kind)} time={at} {text} waiting={kind === 'question'} />
    <TaskManagerBubble {kind} layout="row" header author={author(kind)} time={at} {text} limit={90} more />
  {/each}
</div>
