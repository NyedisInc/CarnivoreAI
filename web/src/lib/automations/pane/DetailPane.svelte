
<script lang="ts">
  import { untrack } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Tabs, { panelAttrs, type TabDef } from '../../../opscenter/ui/Tabs.svelte';
  import { closePane, data } from '../page-store.svelte';
  import { claimEscape, escapeTaken } from '../logic/escape';
  import LogTab from './LogTab.svelte';
  import OutputTab from './OutputTab.svelte';
  import OverviewTab from './OverviewTab.svelte';
  import PaneEditor from './PaneEditor.svelte';
  import PaneHead from './PaneHead.svelte';
  import RunsTab from './RunsTab.svelte';
  import { ensurePaneRun, loadPaneRuns, pane, refreshPaneRuns } from './pane-data.svelte';
  import './pane.css';

  const TABS = ['output', 'runs', 'overview', 'log'] as const;
  const paneTabs = $derived<TabDef[]>(TABS.map((id) => ({ id, label: t(`automations.page.pane.tab.${id}`) })));

  const automation = $derived(data.automations.find((a) => a.automation_id === data.selectedId) ?? null);
  const isNew = $derived(data.paneMode === 'new');
  const editing = $derived(data.paneMode === 'edit' || isNew);
  const shown = $derived(data.paneRunId ? (pane.runs.find((r) => r.run_id === data.paneRunId) ?? pane.runs[0] ?? null) : (pane.runs[0] ?? null));
  const fadeKey = $derived(`${data.paneTab}:${data.paneTab === 'output' || data.paneTab === 'log' ? (shown?.run_id ?? '') : ''}`);

  $effect(() => {
    const a = automation;
    if (!data.paneOpen || !a || isNew || data.fixture) return;
    const id = a.automation_id;
    void (a.recent ?? []).map((r) => `${r.run_id}${r.status}`).join(',');
    void a.run_count;
    untrack(() => void (pane.automationId === id ? refreshPaneRuns(id) : loadPaneRuns(id)));
  });

  $effect(() => {
    const runId = data.paneRunId;
    if (runId && pane.status === 'ready' && pane.automationId === data.selectedId) untrack(() => void ensurePaneRun(runId));
  });

  function step(dir: 1 | -1): void {
    const at = shown ? pane.runs.findIndex((r) => r.run_id === shown.run_id) : -1;
    const next = at >= 0 ? pane.runs[at + dir] : undefined;
    if (next) data.paneRunId = next.run_id;
  }

  function openRun(runId: string): void {
    data.paneRunId = runId;
    data.paneTab = 'output';
  }

  function inField(e: Event): boolean {
    return !!(e.target as Element | null)?.closest?.('input, select, textarea, [contenteditable="true"]');
  }

  function keys(e: KeyboardEvent): void {
    if (!data.paneOpen || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'Escape') {
      if (escapeTaken(e)) return;
      claimEscape(e);
      closePane();
    } else if ((e.key === '[' || e.key === ']') && data.paneTab === 'output' && !editing && !inField(e)) {
      e.preventDefault();
      step(e.key === '[' ? 1 : -1);
    }
  }

  let x0: number | null = null;
  let y0 = 0;
  function touchStart(e: TouchEvent): void {
    const t0 = e.touches[0];
    x0 = e.touches.length === 1 && t0 && !(e.target as Element).closest('pre, table, .r-scroll, input, select, textarea') ? t0.clientX : null;
    y0 = t0?.clientY ?? 0;
  }
  function touchEnd(e: TouchEvent): void {
    const t1 = e.changedTouches[0];
    if (x0 === null || !t1 || data.paneTab !== 'output') return;
    const dx = t1.clientX - x0;
    const dy = t1.clientY - y0;
    x0 = null;
    if (Math.abs(dx) > 70 && Math.abs(dy) < 40) step(dx < 0 ? 1 : -1);
  }
</script>


<svelte:window onkeydowncapture={keys} />

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<aside
  class="ap-pn"
  tabindex="-1"
  aria-label={t('automations.page.pane.aria')}
  data-detail-pane
  data-open={data.paneOpen ? '' : undefined}
  data-mode={isNew ? 'new' : undefined}
  ontouchstart={touchStart}
  ontouchend={touchEnd}
>
  <div class="pl-titlebar ap-pn-bar">
    <Button size="sm" data-pane-back data-pane-close aria-label={t('automations.page.pane.back_aria')} onclick={closePane}>{t('automations.page.pane.back')}</Button>
    <span class="pl-label ap-pn-bar-l">{t('automations.page.pane.title')}</span>
    <Button size="sm" data-pane-close data-pane-x onclick={closePane}>{t('automations.page.pane.close')}</Button>
  </div>
  <div class="ap-pn-scroll">
    {#if data.paneOpen || automation || isNew}
      <section class="ap-pn-sec ap-pn-headsec">
        {#if editing}
          <PaneEditor automation={isNew ? null : automation} />
        {:else if automation}
          <PaneHead {automation} />
        {/if}
      </section>
      {#if automation && !isNew}
        <Tabs tabs={paneTabs} active={data.paneTab} onSelect={(id) => (data.paneTab = id as (typeof TABS)[number])} label={t('automations.page.pane.tabs_aria')} idBase="ap-pn" class="ap-pn-tabs" />
        <section class="ap-pn-sec ap-pn-bodysec" {...panelAttrs('ap-pn', data.paneTab)}>
          {#key fadeKey}
            <div class="ap-pn-fade" data-pane-body={data.paneTab}>
              {#if data.paneTab === 'runs'}
                <RunsTab {automation} current={shown?.run_id ?? null} onOpen={openRun} />
              {:else if data.paneTab === 'overview'}
                <OverviewTab {automation} />
              {:else if data.paneTab === 'log'}
                <LogTab {automation} run={shown} />
              {:else}
                <OutputTab {automation} {shown} onStep={step} onNewest={() => (data.paneRunId = null)} />
              {/if}
            </div>
          {/key}
        </section>
      {/if}
    {/if}
  </div>
</aside>
