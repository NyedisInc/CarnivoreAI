
<script lang="ts">
  import { resourcePush } from '../../resource-push/boot';
  import { t } from '../../i18n/index.svelte';
  import Card from '../../base/Card.svelte';
  import List from '../../base/List.svelte';
  import ListRow from '../../base/ListRow.svelte';
  import Segmented from '../../base/Segmented.svelte';
  import State from '../../base/State.svelte';
  import * as api from '../api';
  import { logEventLabel, reasonLabel } from '../format';
  import { pageClock } from '../page-store.svelte';

  type Props = { automation: api.Automation; run: { run_id: string; number: number } | null };
  let { automation, run }: Props = $props();

  const POLL_MS = 15000;
  let lines = $state<api.LogLine[]>([]);
  let all = $state(false);
  const clock = $derived(pageClock());
  const scope = $derived(all || !run ? 'all' : 'run');
  const shown = $derived((scope === 'run' && run ? lines.filter((l) => l.run_id === run.run_id) : lines).slice().reverse());

  $effect(() => {
    const id = automation.automation_id;
    let current = true;
    const read = (): void => {
      void api
        .readLog(id, 200)
        .then((answer) => {
          if (current) lines = answer.lines;
        })
        .catch(() => {
        });
    };
    read();
    const stop = resourcePush().pushOrPoll(read, POLL_MS, ['automation_log']);
    return () => {
      current = false;
      stop();
    };
  });

  function stamp(ts: number): string {
    return `${clock.when(ts).split(' ').slice(0, 2).join(' ')} ${clock.hms12(ts)}`;
  }
</script>

<Card title={t('automations.page.pane.log.title')} compact>
  {#snippet actions()}
    <Segmented
      label={t('automations.page.pane.log.which')}
      options={[
        { value: 'run', label: run ? t('automations.page.pane.log.run_n', { n: run.number }) : t('automations.page.pane.log.this_run'), attrs: { 'data-logscope': 'run' } },
        { value: 'all', label: t('automations.page.pane.log.every'), attrs: { 'data-logscope': 'all' } },
      ]}
      bind:value={() => scope, (next) => (all = next === 'all')}
    />
  {/snippet}
  {#snippet children()}
    {#if shown.length === 0}
      <State inline title={t('automations.log.empty')} data-log-empty />
    {:else}
      <List label={t('automations.page.pane.log.title')} data-log-lines>
        {#each shown as line, i (`${line.ts}-${i}`)}
          <ListRow wrap primary={logEventLabel(line)} secondary={line.reason ? reasonLabel(line.reason) : undefined} meta={stamp(line.ts)} />
        {/each}
      </List>
    {/if}
  {/snippet}
</Card>
