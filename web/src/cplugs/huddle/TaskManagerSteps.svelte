<script lang="ts">
  import { Icon, TaskRows } from '../sdk/ui';
  import { t } from '../sdk';
  import { summarize, type StepsEntry } from './task-manager-steps';

  let { entry, open = false }: { entry: StepsEntry | null; open?: boolean } = $props();

  let expanded = $state(false);
  $effect(() => { expanded = open; });
  const summary = $derived(entry ? summarize(entry) : null);
</script>

{#if entry && summary}
  <div class="hds" data-task-manager-steps data-open={expanded ? 'on' : undefined}>
    <button type="button" class="hds-fold" aria-expanded={expanded} aria-label={t('cplug.huddle.steps.label')}
            onclick={() => (expanded = !expanded)}>
      <Icon name={expanded ? 'chevron-down' : 'chevron-right'} size={10} />
      <span class="hds-count" data-task-manager-steps-count>{t('cplug.huddle.steps.count', { done: summary.done, total: summary.total })}</span>
      {#if summary.now}<span class="hds-now" title={summary.now}>{t('cplug.huddle.steps.now', { text: summary.now })}</span>{/if}
    </button>
    {#if expanded}<div class="hds-list" data-task-manager-steps-list><TaskRows tasks={entry.tasks} /></div>{/if}
  </div>
{/if}

<style>
  @layer components {
    .hds {
      min-width: 0;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
    }

    .hds-fold {
      display: flex;
      align-items: baseline;
      gap: var(--oc-space-2);
      width: 100%;
      min-width: 0;
      padding: 0;
      border: 0;
      background: none;
      color: var(--oc-text-secondary);
      font: inherit;
      letter-spacing: 0.06em;
      text-align: left;
      cursor: pointer;
    }

    .hds-count {
      flex: none;
      color: var(--oc-text-dim);
    }

    .hds-now {
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      color: var(--oc-green);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hds-list {
      margin-top: var(--oc-space-1);
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
    }
  }
</style>
