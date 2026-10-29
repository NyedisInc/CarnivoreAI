
<script lang="ts">
  import { t } from '../../lib/i18n/index.svelte';
  import { compact } from '../lib/format';
  import type { ActivityRow } from '../lib/run-queue';

  interface Props {
    running: readonly ActivityRow[];
    queue: readonly ActivityRow[];
    more: number;
    queued: number;
  }

  const { running, queue, more, queued }: Props = $props();
</script>

{#snippet rows(list: readonly ActivityRow[], none: string)}
  {#if list.length === 0}
    <p class="oc-rq-none" data-rq-none>{none}</p>
  {:else}
    <ul class="oc-rq-rows">
      {#each list as row (row.id)}
        <li class="oc-rq-row" data-rq-row={row.id} data-tone={row.tone}>
          <bdi class="oc-rq-name">{row.name}</bdi>
          <bdi class="oc-rq-area">{row.area}</bdi>
          <span class="oc-rq-time" data-rq-time>{row.time}</span>
        </li>
      {/each}
    </ul>
  {/if}
{/snippet}

<div class="oc-rq" data-run-queue>
  <section class="oc-rq-section" data-rq-section="running">
    <h4 class="oc-rq-head">
      <span>{t('opscenter.activity.running')}</span>
      <span class="oc-rq-count" data-rq-count>{compact(running.length)}</span>
    </h4>
    {@render rows(running, t('opscenter.activity.none_running'))}
  </section>
  <section class="oc-rq-section" data-rq-section="queue">
    <h4 class="oc-rq-head">
      <span>{t('opscenter.activity.queue')}</span>
      <span class="oc-rq-count" data-rq-count>{compact(queued)}</span>
    </h4>
    {@render rows(queue, t('opscenter.activity.none_queued'))}
    {#if more > 0}
      <p class="oc-rq-more" data-rq-more>{t('opscenter.activity.more', { count: compact(more) })}</p>
    {/if}
  </section>
</div>
