<script lang="ts">
  import { t } from '../../../lib/i18n/index.svelte';
  import { Button, List, ListRow, State, Switch } from '../../../lib/base';
  import { updateAutomation, type Automation } from '../../../lib/automations/api';
  import { cronWords } from '../../../lib/automations/cron-words';
  import { lastRunLine, refusalText, whenLabel } from '../../../lib/automations/format';
  import { openAutomationEdit } from '../../../lib/automations/schedule-prefill';

  let { automations }: { automations: readonly Automation[] } = $props();

  let busyId = $state<string | null>(null);
  let notice = $state('');

  const failed = (a: Automation): boolean => a.last_run?.status === 'failed';

  async function toggle(automation: Automation, next: boolean): Promise<void> {
    busyId = automation.automation_id;
    notice = '';
    try {
      await updateAutomation(automation.automation_id, automation.revision, { enabled: next });
    } catch (error) {
      notice = refusalText(error);
    } finally {
      busyId = null;
    }
  }
</script>

<List label={t('opscenter.cell.automations.list')}>
  {#snippet children()}
    {#each automations as automation (automation.automation_id)}
      {@const last = automation.last_run}
      <ListRow wrap data-automation-row={automation.automation_id} data-enabled={automation.enabled ? 'on' : 'off'}>
        {#snippet children()}
          <span class="oc-aut-main">
            <Button variant="row" data-aut-name onclick={() => openAutomationEdit(automation.automation_id)}>{automation.name}</Button>
            <span class="oc-aut-line" data-aut-schedule>{cronWords(automation.trigger.cron)}</span>
            <span class="oc-aut-line" data-aut-next>{automation.enabled && automation.next_fire_at != null ? t('automations.next_fire', { when: whenLabel(automation.next_fire_at) }) : t('automations.next_none')}</span>
            <span class="oc-aut-line" data-aut-last data-failed={failed(automation) ? '' : undefined}>{t('automations.last_run')}: {last ? lastRunLine(last) : t('automations.never_run')}</span>
          </span>
        {/snippet}
        {#snippet actions()}
          <Switch label="" bare checked={automation.enabled} disabled={busyId === automation.automation_id}
            aria-label={t('automations.switch_aria', { name: automation.name })} data-automation-switch=""
            onchange={(next) => void toggle(automation, next)} />
        {/snippet}
      </ListRow>
    {/each}
  {/snippet}
</List>
{#if notice}<State kind="error" inline data-aut-notice title={notice} />{/if}

<style>
  @layer components {
    .oc-aut-main { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; font-family: var(--font-mono); }

    .oc-aut-line { color: var(--oc-text-dim); font-size: var(--oc-fs-label); overflow-wrap: anywhere; }

    .oc-aut-line[data-failed] { color: var(--oc-coral); }

    :global(.oc-list__row[data-enabled='off']) [data-aut-name] { color: var(--oc-text-dim); }
  }
</style>
