<script lang="ts">
  import { t } from '../sdk';
  import { Icon } from '../sdk/ui';
  import { nudgeInboxEntry } from './huddle.svelte';
  import type { TaskManagerInboxEntry } from './huddle-model';

  const LABELS: Record<TaskManagerInboxEntry['status'], string> = {
    queued: 'cplug.huddle.inbox.queued', filing: 'cplug.huddle.inbox.filing', stuck: 'cplug.huddle.inbox.stuck',
  };

  let { entry }: { entry: TaskManagerInboxEntry } = $props();
  let sending = $state(false);

  async function nudge(): Promise<void> {
    if (sending) return;
    sending = true;
    try {
      await nudgeInboxEntry(entry);
    } finally {
      sending = false;
    }
  }
</script>

<div class="tkm-inbox" data-task-manager-inbox={entry.id} data-status={entry.status} role="status">
  <span class="tkm-inbox-label">{t(LABELS[entry.status])}</span>
  <span class="tkm-inbox-text" data-task-manager-inbox-text={entry.id}>{entry.text}</span>
  {#if entry.status === 'stuck'}
    <button type="button" class="oc-ibtn oc-ibtn--bare tkm-inbox-nudge" data-task-manager-inbox-nudge={entry.id} disabled={sending}
            title={t('cplug.huddle.inbox.nudge')} aria-label={t('cplug.huddle.inbox.nudge')} onclick={() => void nudge()}><Icon name="send" size={12} strokeWidth={1.75} /></button>
  {/if}
</div>

<style>
  @layer components {
    .tkm-inbox {
      display: flex;
      min-width: 0;
      align-items: baseline;
      gap: var(--oc-space-2);
      padding: var(--oc-space-1) var(--oc-space-2);
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-body);
    }
    .tkm-inbox-label {
      flex: none;
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .tkm-inbox-nudge {
      flex: none;
      align-self: center;
      margin-inline-start: auto;
    }
    .tkm-inbox-text {
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-muted);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
</style>
