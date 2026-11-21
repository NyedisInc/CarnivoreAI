<script lang="ts">
  import { type VisitorRevisionAnswers } from './board-visitor-revisions.svelte';
import { t } from '../sdk';
  import type { BoardRevision } from './board-model';
  import { payloadLines } from './visitor-lines';

  let { revision, row }: { revision: BoardRevision; row: VisitorRevisionAnswers } = $props();
  const lines = $derived(payloadLines(revision, row.body));
</script>

<section class="rb-uanswers" data-visitor-answers={row.label}>
  <p class="rb-uline"><span class="rb-ubadge">{row.label}</span>
    {t('cplug.reviewboard.visitors.panel', { label: row.label, id: revision.id })}</p>
  {#if lines.length === 0}
    <p class="rb-uline">{t('cplug.reviewboard.visitors.nothing')}</p>
  {/if}
  {#each lines as line (line.id)}
    <p class="rb-uline" data-visitor-line={line.id}><span class="rb-label">{line.label}</span> {line.value}</p>
    {#if line.note}<p class="rb-uline">{t('cplug.reviewboard.visitors.note', { note: line.note })}</p>{/if}
  {/each}
</section>
