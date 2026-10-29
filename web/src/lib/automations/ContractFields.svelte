
<script lang="ts">
  import type { Misfire, ProjectChoice } from './api';
  import { t } from '../i18n/index.svelte';
  import NumberField from '../base/NumberField.svelte';
  import Select from '../base/Select.svelte';
  import FieldHint from './schedule/FieldHint.svelte';

  interface Props {
    projectId: number | null;
    misfire: Misfire;
    retryMax: number;
    backoffMin: number | null;
    runtimeMin: number | null;
    projects: ProjectChoice[];
  }
  let {
    projectId = $bindable(),
    misfire = $bindable(),
    retryMax = $bindable(),
    backoffMin = $bindable(),
    runtimeMin = $bindable(),
    projects,
  }: Props = $props();
</script>

<div class="auto-form__group" data-contract-fields>
  <div class="auto-form__row">
    <div class="auto-fld ap-pn-wide">
      <Select
        label={t('automations.field.project')}
        data-auto-field="project"
        value={projectId === null ? '' : String(projectId)}
        onchange={(e) => (projectId = e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}
      >
        {#snippet children()}
          <option value="">{t('automations.project.none')}</option>
          {#each projects as project (project.id)}
            {#if project.id !== null}<option value={String(project.id)}>{project.name}</option>{/if}
          {/each}
        {/snippet}
      </Select>
      <FieldHint field="project" text={t('automations.simple.hint.project')} eg={t('automations.simple.hint.project_eg')} onFill={() => (projectId = null)} />
    </div>
    <div class="auto-fld ap-pn-wide">
      <Select
        label={t('automations.field.misfire')}
        data-auto-field="misfire"
        value={misfire}
        options={[{ value: 'run_once', label: t('automations.misfire.run_once') }, { value: 'skip', label: t('automations.misfire.skip') }]}
        onchange={(e) => (misfire = e.currentTarget.value as Misfire)}
      />
      <FieldHint field="misfire" text={t('automations.simple.hint.misfire')} eg={t('automations.misfire.skip')} onFill={() => (misfire = 'skip')} />
    </div>
  </div>
  <div class="auto-form__row">
    <div class="auto-fld">
      <Select
        label={t('automations.field.retry_max')}
        data-auto-field="retry_max"
        value={String(retryMax)}
        options={[0, 1, 2, 3].map((count) => ({ value: String(count), label: String(count) }))}
        onchange={(e) => (retryMax = Number(e.currentTarget.value))}
      />
      <FieldHint field="retry_max" text={t('automations.simple.hint.retry_max')} eg={t('automations.simple.hint.retry_max_eg')} onFill={(eg) => (retryMax = Number(eg))} />
    </div>
    <div class="auto-fld">
      <NumberField label={t('automations.field.retry_backoff')} data-auto-field="retry_backoff" min={1} max={60} disabled={retryMax === 0} bind:value={backoffMin} />
      <FieldHint field="retry_backoff" text={t('automations.simple.hint.retry_backoff')} eg={t('automations.simple.hint.retry_backoff_eg')} onFill={(eg) => (backoffMin = Number(eg))} />
    </div>
    <div class="auto-fld ap-pn-wide">
      <NumberField label={t('automations.field.max_runtime')} data-auto-field="max_runtime" min={1} max={1440} placeholder={t('automations.runtime.none')} bind:value={runtimeMin} />
      <FieldHint field="max_runtime" text={t('automations.simple.hint.max_runtime')} eg={t('automations.simple.hint.max_runtime_eg')} onFill={(eg) => (runtimeMin = Number(eg))} />
    </div>
  </div>
  <span class="auto-form__note">{t('automations.contract.note')}</span>
</div>
