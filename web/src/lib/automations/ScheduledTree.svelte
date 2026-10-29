
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { openTaskManagerItem } from '../task-manager-reveal/reveal';
  import { taskManagerAddonOn } from '../task-manager-schedules/task-manager-addon.svelte';
  import { data, sessionOptions, wantSessions } from './page-store.svelte';
  import './scheduled-tree.css';
  import { countWords } from './logic/words';
  import { buildScheduledTree, type SchedNode } from './scheduled-tree';
  import { followScheduled, loadScheduled, scheduled } from './scheduled-store.svelte';
  import TreeScheduledRow from './TreeScheduledRow.svelte';

  const nodes = $derived(scheduled.rows.length === 0 ? [] : buildScheduledTree(data.projects, sessionOptions(), scheduled.rows));

  $effect(() => (data.fixture ? undefined : followScheduled()));
  $effect(() => {
    if (!data.fixture && taskManagerAddonOn() && scheduled.rows.length > 0 && !data.sessionsWanted) void wantSessions();
  });

  const countOf = (n: SchedNode): number => n.schedules.length + n.children.reduce((sum, c) => sum + countOf(c), 0);

  const total = $derived(nodes.reduce((sum, n) => sum + countOf(n), 0));

  function nameOf(n: SchedNode): string {
    if (n.kind === 'unassigned') return t('automations.tree.unassigned');
    return n.label || t('automations.tree.unnamed_session');
  }

  async function open(list: string, id: number): Promise<void> {
    data.notice = (await openTaskManagerItem(list, id)) ?? '';
  }
</script>

{#snippet branch(n: SchedNode, depth: number)}
  <li class="ap-st-node" data-tree-node={n.key} data-tree-kind={n.kind} data-depth={depth}>
    <div class="ap-st-head"><span class="ap-st-nm" data-tree-name>{nameOf(n)}</span><span class="ap-st-n ap-num">{countOf(n)}</span></div>
    {#if n.schedules.length > 0}
      <ul class="ap-st-items" data-tree-huddle>
        {#each n.schedules as schedule (schedule.item)}
          <TreeScheduledRow {schedule} onOpen={open} onChanged={loadScheduled} />
        {/each}
      </ul>
    {/if}
    {#if n.children.length > 0}
      <ul class="ap-st-kids">
        {#each n.children as child (child.key)}{@render branch(child, depth + 1)}{/each}
      </ul>
    {/if}
  </li>
{/snippet}

{#if taskManagerAddonOn() && (nodes.length > 0 || !scheduled.answered)}
  <section class="ap-st" data-scheduled-tree aria-label={t('automations.page.sched.aria')} aria-busy={nodes.length === 0}>
    <div class="ap-st-title">
      <span class="pl-label">{t('automations.page.sched.title')}</span>
      {#if nodes.length > 0}
        <span class="ap-st-total ap-num">{countWords('automations.page.sched.count', total)}</span>
      {:else}
        <span class="ap-st-total" role="status" data-scheduled-reading>{t('automations.page.sched.reading')}</span>
      {/if}
    </div>
    {#if nodes.length > 0}
      <div class="ap-st-cols" aria-hidden="true">
        <span>{t('automations.page.sched.col.item')}</span>
        <span class="ap-st-c-tag"></span>
        <span>{t('automations.page.col.next')}</span>
        <span class="ap-st-c-rep">{t('automations.page.sched.col.repeat')}</span>
        <span></span>
      </div>
      <ul class="ap-st-tree">
        {#each nodes as n (n.key)}{@render branch(n, 0)}{/each}
      </ul>
    {/if}
  </section>
{/if}
