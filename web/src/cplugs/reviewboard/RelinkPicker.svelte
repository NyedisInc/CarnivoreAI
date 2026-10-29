<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../sdk';
  import { Icon } from '../sdk/ui';
  import { fetchTasks } from './board-api';
  import type { TaskChoice } from './board-model';

  let { list, current, onpick, onclose }: { list: string; current: number | null; onpick: (id: number) => void; onclose: () => void } = $props();

  let tasks = $state<TaskChoice[]>([]);
  let failed = $state(false);
  let loading = $state(true);

  onMount(() => {
    void fetchTasks(list).then(
      (found) => {
        tasks = found;
        loading = false;
      },
      () => {
        failed = true;
        loading = false;
      },
    );
  });
</script>

<section class="rb-round-card" data-relink>
  <header class="rb-card-head">
    <span class="rb-label">{t('cplug.reviewboard.relink.title')}</span>
    <button type="button" class="rb-icon" aria-label={t('cplug.reviewboard.action.close')} title={t('cplug.reviewboard.action.close')}
            data-relink-close onclick={onclose}><Icon name="close" size={14} /></button>
  </header>
  {#if loading}
    <p class="rb-note-text" role="status">{t('cplug.reviewboard.page.loading')}</p>
  {:else if failed}
    <p class="rb-warn" role="status">{t('cplug.reviewboard.relink.failed')}</p>
  {:else if tasks.length === 0}
    <p class="rb-note-text">{t('cplug.reviewboard.relink.none')}</p>
  {:else}
    <ul class="rb-list">
      {#each tasks as task (task.id)}
        <li>
          <button type="button" class="rb-row" data-relink-item={task.id} aria-current={task.id === current} onclick={() => onpick(task.id)}>
            <span class="rb-row-title">{task.title}</span>
            <span class="rb-row-meta">#{task.id}</span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</section>
