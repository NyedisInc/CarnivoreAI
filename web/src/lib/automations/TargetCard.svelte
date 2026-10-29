
<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import State from '../base/State.svelte';
  import Field from '../base/Field.svelte';
  import Select from '../base/Select.svelte';
  import Switch from '../base/Switch.svelte';
  import type { AutomationTarget, ProjectChoice } from './api';
  import { listProjectChoices } from './api';

  let { target = $bindable() }: { target: AutomationTarget } = $props();

  const TITLE_MAX = 120;
  const SUMMARY_MAX = 200;

  let projects = $state<ProjectChoice[] | null>(null);
  let failed = $state(false);

  const withId = $derived((projects ?? []).filter((p) => p.id != null));
  const title = $derived(String(target.title ?? ''));
  const summary = $derived(String(target.summary ?? ''));

  onMount(async () => {
    try {
      projects = await listProjectChoices();
    } catch {
      failed = true;
      projects = [];
    }
  });

  $effect(() => {
    const first = withId[0];
    if (first && target.project_id == null) target = { ...target, project_id: first.id };
  });

  function set(field: string, value: unknown): void {
    target = { ...target, [field]: value };
  }
</script>

{#if projects === null}
  <p class="auto-form__note" role="status">{t('automations.card.loading')}</p>
{:else if failed}
  <State kind="error" inline title={t('automations.card.unavailable')} />
{:else if withId.length === 0}
  <p class="auto-form__note" role="status">{t('automations.card.none')}</p>
{:else}
  <Select
    label={t('automations.card.project')}
    data-card-project
    value={String(target.project_id ?? '')}
    options={withId.map((project) => ({ value: String(project.id), label: project.name }))}
    onchange={(e) => set('project_id', Number(e.currentTarget.value))}
  />
  <div class="auto-fld">
    <Field label={t('automations.card.title')} data-card-title autocomplete="off" value={title} oninput={(e) => set('title', e.currentTarget.value)} />
    <span class="auto-form__note" data-card-title-count>{t('automations.card.count', { used: title.length, max: TITLE_MAX })}</span>
  </div>
  <div class="auto-fld">
    <Field label={t('automations.card.summary')} data-card-summary autocomplete="off" value={summary} oninput={(e) => set('summary', e.currentTarget.value)} />
    <span class="auto-form__note" data-card-summary-count>{t('automations.card.count', { used: summary.length, max: SUMMARY_MAX })}</span>
  </div>
  <Field label={t('automations.card.text')} multiline rows={4} data-card-text value={String(target.text ?? '')} oninput={(e) => set('text', e.currentTarget.value)} />
  <div class="auto-fld">
    <Field label={t('automations.card.validate')} multiline rows={3} data-card-validate value={String(target.how_to_validate ?? '')} oninput={(e) => set('how_to_validate', e.currentTarget.value)} />
    <span class="auto-form__note">{t('automations.card.tokens_note', { date: '{date}', week: '{week}' })}</span>
  </div>
  <Switch label={t('automations.card.queued_label')} data-card-queued="" bind:checked={() => target.queued === true, (next) => set('queued', next)} />
{/if}
