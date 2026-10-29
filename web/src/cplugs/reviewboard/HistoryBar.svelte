<script lang="ts">
  /* could not */
  import { tick } from 'svelte';
  import { t } from '../sdk';
  import type { HistoryItem } from './board-model';
  import { isLiveDraft } from './live-model';

  interface Props {
    items: HistoryItem[];
    folded: { from: number; to: number } | null;
    current: string;
    total: number;
    onpick: (revision: string) => void;
    onround?: (round: string) => void;
    onunfold: () => void;
  }

  let { items, folded, current, total, onpick, onround, onunfold }: Props = $props();

  let track = $state<HTMLDivElement | null>(null);

  function revisionLabel(item: HistoryItem): string {
    if (isLiveDraft(item.id)) return t('cplug.reviewboard.history.draft');
    if (item.milestone) return t('cplug.reviewboard.history.milestone', { id: item.id, name: item.milestone });
    return t('cplug.reviewboard.history.revision', { id: item.id });
  }

  $effect(() => {
    void items.length;
    void tick().then(() => {
      if (track) track.scrollLeft = track.scrollWidth;
    });
  });
</script>

<div class="rb-history" data-board-history>
  <div class="rb-track" bind:this={track} role="group" aria-label={t('cplug.reviewboard.history.label')}>
    {#if folded}
      <button type="button" class="rb-step rb-step--fold" aria-label={t('cplug.reviewboard.history.folded_label')} onclick={onunfold}>
        {t('cplug.reviewboard.history.folded', { from: folded.from, to: folded.to })}
      </button>
    {/if}
    {#each items as item (`${item.kind}:${item.id}`)}
      {#if item.kind === 'revision'}
        <button type="button" class="rb-step" aria-current={item.id === current} aria-label={revisionLabel(item)} title={item.milestone ?? undefined}
                data-history="revision" data-live-draft={isLiveDraft(item.id) ? '' : undefined} data-milestone={item.milestone ? '' : undefined} onclick={() => onpick(item.id)}>{item.id}</button>
      {:else}
        <button type="button" class="rb-round" data-undelivered={item.undelivered} data-history="round"
                aria-label={t(item.undelivered ? 'cplug.reviewboard.history.round_undelivered' : 'cplug.reviewboard.history.round', { id: item.id, revision: item.revision })}
                onclick={() => {
                  onpick(item.revision);
                  onround?.(item.id);
                }}></button>
      {/if}
    {/each}
  </div>
  <span class="rb-count">{t('cplug.reviewboard.history.stepper', { id: current, total })}</span>
</div>
