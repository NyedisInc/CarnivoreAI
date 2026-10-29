<script lang="ts">
  import { tick } from 'svelte';
  import { t } from '../sdk';
  import { Button, IconButton } from '../sdk/ui';
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
      <Button size="sm" data-history="fold" aria-label={t('cplug.reviewboard.history.folded_label')} onclick={onunfold}>
        {t('cplug.reviewboard.history.folded', { from: folded.from, to: folded.to })}
      </Button>
    {/if}
    {#each items as item (`${item.kind}:${item.id}`)}
      {#if item.kind === 'revision'}
        <Button size="sm" aria-current={item.id === current} aria-label={revisionLabel(item)} title={item.milestone ?? undefined}
                data-history="revision" data-live-draft={isLiveDraft(item.id) ? '' : undefined} data-milestone={item.milestone ? '' : undefined} onclick={() => onpick(item.id)}>{item.id}</Button>
      {:else}
        <IconButton variant="quiet" data-undelivered={item.undelivered} data-history="round"
                    label={t(item.undelivered ? 'cplug.reviewboard.history.round_undelivered' : 'cplug.reviewboard.history.round', { id: item.id, revision: item.revision })}
                    onclick={() => {
                      onpick(item.revision);
                      onround?.(item.id);
                    }}><span class="rb-diamond" aria-hidden="true"></span></IconButton>
      {/if}
    {/each}
  </div>
  <span class="rb-count">{t('cplug.reviewboard.history.stepper', { id: current, total })}</span>
</div>
