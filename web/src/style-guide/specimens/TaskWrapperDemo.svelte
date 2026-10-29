<script lang="ts">
  /* padding */
  import TaskWrapper from '../../lib/base/TaskWrapper.svelte';
  import type { TaskState } from '../../lib/base/task-wrapper';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import Tabs, { panelAttrs, type TabDef } from '../../opscenter/ui/Tabs.svelte';

  interface Sample { id: string; title: string; icon: string; color: string; meta: string; said: string; state: TaskState }
  const SAMPLES: Sample[] = [
    { id: 'review', title: 'check the tab strip at phone width', icon: 'status-review', color: 'var(--oc-cyan)', meta: '2 messages', said: 'ready for your look: the strip collapses to icons at 320px', state: 'compact' },
    { id: 'opened', title: 'ship the wrapper', icon: 'status-working', color: 'var(--oc-green)', meta: 'today 14:00', said: 'building the state store now', state: 'opened' },
    { id: 'detailed', title: 'which db for the queue?', icon: 'status-question', color: 'var(--oc-yellow-bright)', meta: 'asking', said: 'postgres or sqlite. postgres scales past one writer; sqlite keeps the install to one file. the whole message shows here, nothing clamped.', state: 'detailed' },
  ];
  const TABS: TabDef[] = [
    { id: 'action', label: 'action', icon: 'bolt' },
    { id: 'discussion', label: 'discussion', icon: 'chat' },
    { id: 'details', label: 'details', icon: 'info' },
    { id: 'subtasks', label: 'subtasks', icon: 'list' },
  ];
  let states = $state<Record<string, TaskState>>(Object.fromEntries(SAMPLES.map((s) => [s.id, s.state])));
  let tab = $state('action');
  const idBase = $props.id();
</script>

<div class="sg-tw">
  {#each SAMPLES as sample (sample.id)}
    <TaskWrapper state={states[sample.id] as TaskState} onStateChange={(next) => (states[sample.id] = next)} toggleProps={{ 'aria-label': sample.title }}>
      {#snippet head()}
        <span class="sg-tw__icon" style:color={sample.color}><Icon name={sample.icon} size={14} strokeWidth={2} /></span>
        <span class="sg-tw__title">{sample.title}</span>
        <span class="sg-tw__meta">{sample.meta}</span>
      {/snippet}
      {#snippet tabs()}
        <Tabs compact collapse tabs={TABS} active={tab} onSelect={(id) => (tab = id)} label="task view" {idBase} />
        <div class="sg-tw__panel" {...panelAttrs(idBase, tab)}>
          <p class="sg-tw__said" class:sg-tw__said--clamped={states[sample.id] === 'opened'}>{tab}: {sample.said}</p>
          <input class="sg-tw__reply" data-field aria-label="reply" placeholder="reply to claude" />
        </div>
      {/snippet}
    </TaskWrapper>
  {/each}
</div>
