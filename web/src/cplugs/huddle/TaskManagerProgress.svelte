<script lang="ts">
  import { t } from '../sdk';
  import { elapsed, ageNow, clip, isStale, PHASE_COLOR } from './huddle-progress';
  import { progressOf, sinceRead } from './task-manager-progress.svelte';

  let { id, full = false }: { id: number; full?: boolean } = $props();

  const lines = $derived(progressOf(id));
  const since = $derived(sinceRead());
</script>

{#if lines.length}
  <ul class="hdp" data-task-manager-progress={id} aria-label={t('cplug.huddle.progress.label')}>
    {#each lines as line (line.worker)}
      {@const stale = isStale(line, since)}
      <li class="hdp-line" class:hdp-line--stale={stale} class:hdp-line--full={full} data-task-manager-progress-worker={line.worker}
          data-phase={line.phase} data-stale={stale ? 'true' : 'false'}>
        <span class="hdp-chip" style:--_phase={PHASE_COLOR[line.phase]}>{t(`cplug.huddle.progress.phase.${line.phase}`)}</span>
        {#if lines.length > 1 || line.worker !== 'main'}<span class="hdp-worker">{line.worker}</span>{/if}
        {#if line.note}<span class="hdp-note" title={line.note}>{full ? line.note : clip(line.note)}</span>{/if}
        <span class="hdp-age">{stale ? t('cplug.huddle.progress.stale', { time: elapsed(ageNow(line, since)) }) : elapsed(ageNow(line, since))}</span>
      </li>
    {/each}
  </ul>
{/if}

<style>
  @layer components {
    .hdp {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
      margin: 0;
      padding: 0;
      list-style: none;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
    }

    .hdp-line {
      display: flex;
      align-items: baseline;
      gap: var(--oc-space-2);
      min-width: 0;
      color: var(--oc-text-secondary);
    }

    .hdp-line--stale {
      opacity: 0.55;
    }

    .hdp-chip {
      flex: none;
      padding: 0 var(--oc-space-1);
      border: 1px solid var(--_phase);
      border-radius: var(--oc-radius-sm);
      color: var(--_phase);
      letter-spacing: 0.06em;
      line-height: var(--oc-space-4);
    }

    .hdp-worker {
      flex: none;
      color: var(--oc-text-muted);
    }

    .hdp-note {
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hdp-line--full .hdp-note {
      overflow: visible;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .hdp-age {
      flex: none;
      margin-left: auto;
      color: var(--oc-text-dim);
    }
  }
</style>
