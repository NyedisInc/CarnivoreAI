<script lang="ts">
  import { badgeText, badgeTitle, runningCount } from './subagents';
  import { openSubagentList } from './popup';

  let {
    running,
    total = null,
    sessionId = '',
    name = '',
    rollup = false,
    rollupTitle = '',
  }: {
    running: number | null | undefined;
    total?: number | null;
    sessionId?: string;
    name?: string;
    rollup?: boolean;
    rollupTitle?: string;
  } = $props();

  const count = $derived(runningCount(running));
  const title = $derived(count === null ? '' : rollup ? rollupTitle : badgeTitle(count, total));

  function open(event: MouseEvent): void {
    event.stopPropagation();
    event.preventDefault();
    openSubagentList(event.currentTarget as HTMLElement, sessionId, name);
  }

  function keep(event: KeyboardEvent): void {
    if (event.key === 'Enter' || event.key === ' ') event.stopPropagation();
  }
</script>

{#if count !== null}
  {#if rollup}
    <span class="subagent-count subagent-count--rollup" {title} data-subagents-rollup>{badgeText(count)}</span>
  {:else}
    <button
      type="button"
      class="subagent-count subagent-count--button"
      aria-haspopup="dialog"
      aria-label={title}
      {title}
      data-subagents-session-id={sessionId}
      onclick={open}
      onkeydown={keep}
    >{badgeText(count)}</button>
  {/if}
{/if}
