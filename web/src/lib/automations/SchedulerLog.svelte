
<script lang="ts">
  import Button from '../base/Button.svelte';
  import List from '../base/List.svelte';
  import ListRow from '../base/ListRow.svelte';
  import NumberField from '../base/NumberField.svelte';
  import Select from '../base/Select.svelte';
  import { resourcePush } from '../resource-push/boot';
  import * as api from './api';
  import { t } from '../i18n/index.svelte';
  import { logEventLabel, reasonLabel, refusalText } from './format';
  import { data, pageClock } from './page-store.svelte';

  let { automationId }: { automationId: string | null } = $props();

  const POLL_MS = 15000;
  let lines = $state<api.LogLine[]>([]);
  let settings = $state<api.LogSettings | null>(null);
  let draft = $state<api.LogSettings>({ rotate: 'size', max_mb: 10, keep: 5 });
  let problem = $state('');
  let saved = $state(false);
  let busy = $state(false);

  async function read(id: string | null): Promise<void> {
    try {
      const answer = await api.readLog(id);
      lines = answer.lines;
      if (!settings) {
        settings = answer.settings;
        draft = { ...answer.settings };
      }
      problem = '';
    } catch (error) {
      problem = refusalText(error);
    }
  }

  $effect(() => {
    const id = automationId;
    void read(id);
    return resourcePush().pushOrPoll(() => void read(id), POLL_MS, ['automation_log']);
  });

  async function save(): Promise<void> {
    busy = true;
    saved = false;
    try {
      settings = await api.putLogSettings({ rotate: draft.rotate, max_mb: Number(draft.max_mb), keep: Number(draft.keep) });
      draft = { ...settings };
      saved = true;
      problem = '';
    } catch (error) {
      problem = refusalText(error);
    } finally {
      busy = false;
    }
  }

  const clock = $derived(pageClock());

  function nameOf(line: api.LogLine): string {
    const found = data.automations.find((a) => a.automation_id === line.automation_id)?.name;
    return found ?? (typeof line.name === 'string' && line.name ? line.name : t('automations.page.log.gone'));
  }
</script>

<div class="auto-log" data-scheduler-log>
  <form
    class="auto-form__row"
    data-log-settings
    onsubmit={(e) => {
      e.preventDefault();
      void save();
    }}
  >
    <Select
      label={t('automations.log.rotate')}
      data-log-rotate
      bind:value={draft.rotate}
      options={[
        { value: 'size', label: t('automations.log.rotate.size') },
        { value: 'daily', label: t('automations.log.rotate.daily') },
      ]}
    />
    <NumberField label={t('automations.log.max_mb')} data-log-max-mb min={1} max={500} disabled={draft.rotate !== 'size'} bind:value={draft.max_mb} />
    <NumberField label={t('automations.log.keep')} data-log-keep min={1} max={50} bind:value={draft.keep} />
    <Button type="submit" variant="confirm" data-log-save disabled={busy}>{t('automations.log.save')}</Button>
    {#if saved}<span class="auto-line" role="status">{t('automations.log.saved')}</span>{/if}
  </form>
  {#if problem}<p class="auto-line auto-line--error" role="alert" data-log-problem>{problem}</p>{/if}
  {#if lines.length === 0}
    <p class="auto-line" role="status" data-log-empty>{t('automations.log.empty')}</p>
  {:else}
    <List label={t('automations.page.log.all')} data-log-lines>
      {#each lines as line, index (`${line.ts}-${index}`)}
        <ListRow wrap>
          {#snippet primary()}<span data-log-name>{nameOf(line)}</span>{/snippet}
          {#snippet secondary()}{logEventLabel(line)}{#if line.reason}{' '}{reasonLabel(line.reason)}{/if}{/snippet}
          {#snippet meta()}<span class="ap-num">{clock.when(line.ts)}</span>{/snippet}
        </ListRow>
      {/each}
    </List>
  {/if}
</div>
