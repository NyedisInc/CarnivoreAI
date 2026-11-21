<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../sdk';
  import { Button, Card, IconButton, List, ListRow } from '../sdk/ui';
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

<Card title={t('cplug.reviewboard.relink.title')} compact data-relink>
  {#snippet actions()}
    <IconButton label={t('cplug.reviewboard.action.close')} icon="close" variant="close" iconSize={14} data-relink-close onclick={onclose} />
  {/snippet}
  {#if loading}
    <p class="rb-note-text" role="status">{t('cplug.reviewboard.page.loading')}</p>
  {:else if failed}
    <p class="rb-warn" role="status">{t('cplug.reviewboard.relink.failed')}</p>
  {:else if tasks.length === 0}
    <p class="rb-note-text">{t('cplug.reviewboard.relink.none')}</p>
  {:else}
    <List>
      {#each tasks as task (task.id)}
        <ListRow selected={task.id === current}>
          <Button variant="row" data-relink-item={task.id} aria-current={task.id === current} onclick={() => onpick(task.id)}>
            <span class="rb-row-line">
              <span class="rb-row-title">{task.title}</span>
              <span class="rb-row-meta">#{task.id}</span>
            </span>
          </Button>
        </ListRow>
      {/each}
    </List>
  {/if}
</Card>
