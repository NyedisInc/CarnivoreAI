<script lang="ts">
  import Tabs, { panelAttrs, type TabDef } from '../../opscenter/ui/Tabs.svelte';

  let { many = false, joined = false, collapse = false }: { many?: boolean; joined?: boolean; collapse?: boolean } = $props();

  const base: TabDef[] = [
    { id: 'colors', label: 'colors' },
    { id: 'rows', label: 'sidebar rows', badge: 4 },
    { id: 'status', label: 'status bar', dot: true },
  ];
  const extra: TabDef[] = [
    { id: 'control', label: 'control center' },
    { id: 'terminal', label: 'terminal' },
    { id: 'notify', label: 'notifications' },
  ];
  const iconTabs: TabDef[] = [
    { id: 'action', label: 'action', icon: 'bolt' },
    { id: 'discussion', label: 'discussion', icon: 'chat', badge: '2 new' },
    { id: 'details', label: 'details', icon: 'info' },
    { id: 'subtasks', label: 'subtasks', icon: 'list' },
  ];
  const tabs = $derived(collapse ? iconTabs : many ? [...base, ...extra] : base);
  let active = $state(collapse ? 'action' : 'colors');
  const idBase = $props.id();
</script>

<div class="sg-page-tabs" class:sg-page-tabs--joined={joined || collapse}>
  <Tabs {joined} compact={collapse} {collapse} {tabs} {active} onSelect={(id) => (active = id)} label="demo tabs" {idBase} />
  <div class="sg-page-tabs__panel" {...panelAttrs(idBase, active)}>panel: {active}</div>
</div>

<style>
  .sg-page-tabs {
    border: 1px solid var(--oc-line-rule);
    background: var(--oc-ground-page);
    color: var(--oc-text-secondary);
    font: var(--oc-fs-body, 12px) / 1.4 var(--oc-font, var(--font-mono));
  }

  .sg-page-tabs--joined {
    background: var(--oc-ground-panel);
  }

  .sg-page-tabs__panel {
    padding: var(--oc-space-3);
  }
</style>
