<script lang="ts">
  import { roundOpener, t } from '../sdk';
  import { Icon } from '../sdk/ui';
  import type { TaskManagerBoardRound } from './huddle-model';

  let { round, text }: { round: TaskManagerBoardRound; text: string } = $props();

  const lines = $derived(text.split('\n').filter((l) => !l.startsWith('read it: task_manager_board_get')));
  const head = $derived(lines[0]);
  const rest = $derived(lines.slice(1));

  const opener = roundOpener();

  async function open(): Promise<void> {
    try {
      await opener?.({ slug: round.slug, revision: round.revision });
    } catch {
    }
  }
</script>

<div class="hdrc" data-task-manager-round={round.round}>
  <div class="hdrc-text">
    <span class="hdrc-title">{head ?? t('cplug.huddle.round.card', { id: round.round, revision: round.revision })}</span>
    {#each rest as line, i (i)}<span class="hdrc-line">{line}</span>{/each}
  </div>
  {#if opener}
  <button type="button" class="hdrc-open" aria-label={t('cplug.huddle.round.open', { revision: round.revision })}
          title={t('cplug.huddle.round.open', { revision: round.revision })} data-task-manager-round-open={round.round} onclick={() => void open()}>
    <Icon name="external" size={16} />
  </button>
  {/if}
</div>

<style>
  @layer components {
    .hdrc {
      display: flex;
      align-items: flex-start;
      gap: var(--oc-space-3);
      min-width: 0;
      margin: var(--oc-space-1) 0 0;
      padding: var(--oc-space-2) var(--oc-space-3);
      border: 1px solid var(--oc-control-line);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-field);
      font-family: var(--font-mono);
    }

    .hdrc-text { display: flex; flex: 1; flex-direction: column; gap: 2px; min-width: 0; }
    .hdrc-title { color: var(--oc-text-primary); font-size: var(--oc-fs-label); overflow-wrap: anywhere; }
    .hdrc-line { color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); overflow-wrap: anywhere; }

    .hdrc-open {
      --_bd: transparent;
      display: inline-grid;
      flex: none;
      place-items: center;
      box-sizing: border-box;
      width: 28px;
      height: 28px;
      padding: 0;
      border: 1px solid var(--_bd);
      border-radius: var(--oc-radius-sm);
      background: transparent;
      color: var(--oc-text-secondary);
      cursor: pointer;
    }

    .hdrc-open:hover { --_bd: var(--oc-line-frame); background: var(--oc-ground-hover); color: var(--oc-text-primary); }
  }
</style>
