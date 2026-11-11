<script lang="ts">
  import { tick } from 'svelte';
  import { t } from '../sdk';
  import { Button, IconButton } from '../sdk/ui';
  import type { VisitorRevision } from './board-visitor-revisions.svelte';
  import type { HistoryItem } from './board-model';
  import { visitorsOf } from './visitor-lines';
  import { isLiveDraft } from './live-model';

  interface Props {
    items: HistoryItem[];
    folded: { from: number; to: number } | null;
    current: string;
    total: number;
    onpick: (revision: string) => void;
    onround?: (round: string) => void;
    onunfold: () => void;
    visitors?: VisitorRevision[];
    openVisitor?: number | null;
    onvisitor?: (row: VisitorRevision) => void;
  }

  let { items, folded, current, total, onpick, onround, onunfold, visitors = [], openVisitor = null, onvisitor }: Props = $props();

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
        {#each visitorsOf(visitors, item.id) as row (row.number)}
          <Button size="sm" data-history="visitor" data-visitor={row.label} data-present={row.present ? '' : undefined}
                  aria-current={item.id === current && openVisitor === row.number}
                  aria-label={t(row.present ? 'cplug.reviewboard.history.visitor_here' : 'cplug.reviewboard.history.visitor', { label: row.label, id: item.id })}
                  onclick={() => onvisitor?.(row)}><span class="rb-ubadge">u</span>{row.number}{#if row.present}<span class="rb-upresent" aria-hidden="true"></span>{/if}</Button>
        {/each}
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
