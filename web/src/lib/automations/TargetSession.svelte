
<script lang="ts">
  import { onMount } from 'svelte';
  import * as api from './api';
  import type { AutomationTarget, ProjectChoice } from './api';
  import { t } from '../i18n/index.svelte';
  import Field from '../base/Field.svelte';
  import Select from '../base/Select.svelte';
  import State from '../base/State.svelte';

  let { target = $bindable(), projects }: { target: AutomationTarget; projects: ProjectChoice[] } = $props();

  let sessions = $state<api.SessionChoice[] | null>(null);
  let failed = $state(false);

  const choices = $derived((sessions ?? []).filter((s) => s.session_uuid && !s.archived_at));

  onMount(async () => {
    try {
      sessions = await api.listSessionRecords();
    } catch {
      // could not
      failed = true;
      sessions = [];
    }
  });

  function pick(uuid: string): void {
    const found = choices.find((s) => s.session_uuid === uuid);
    target = { ...target, session_uuid: uuid, session_name: found?.name ?? found?.tmux_name ?? '' };
  }

  function set(key: string, value: unknown): void {
    target = { ...target, [key]: value };
  }
</script>

{#if sessions === null}
  <p class="auto-form__note" role="status">{t('automations.session.loading')}</p>
{:else}
  {#if failed}<State kind="error" inline title={t('automations.session.unavailable')} />{/if}
  <Select label={t('automations.session.field')} data-session-select value={(target.session_uuid as string) ?? ''} onchange={(e) => pick(e.currentTarget.value)}>
    {#snippet children()}
      <option value="" disabled>{t('automations.session.pick')}</option>
      {#if target.session_uuid && !choices.some((s) => s.session_uuid === target.session_uuid)}
        <option value={target.session_uuid as string}>{(target.session_name as string) || (target.session_uuid as string)}</option>
      {/if}
      {#each choices as session (session.session_uuid)}
        <option value={session.session_uuid}>{session.name ?? session.tmux_name ?? session.session_uuid}</option>
      {/each}
    {/snippet}
  </Select>
  <Field
    label={t('automations.session.text')}
    multiline
    rows={4}
    maxlength={20000}
    data-session-text
    value={(target.text as string) ?? ''}
    oninput={(e) => set('text', e.currentTarget.value)}
  />
  <div class="auto-form__row">
    <div class="auto-fld">
      <Select
        label={t('automations.session.if_asleep')}
        data-session-if-asleep
        value={target.if_asleep as string}
        options={[{ value: 'wake', label: t('automations.session.if_asleep.wake') }, { value: 'skip', label: t('automations.session.if_asleep.skip') }]}
        onchange={(e) => set('if_asleep', e.currentTarget.value)}
      />
    </div>
    <div class="auto-fld">
      <Select
        label={t('automations.session.if_gone')}
        data-session-if-gone
        value={target.if_gone as string}
        options={[{ value: 'start', label: t('automations.session.if_gone.start') }, { value: 'fail', label: t('automations.session.if_gone.fail') }]}
        onchange={(e) => set('if_gone', e.currentTarget.value)}
      />
    </div>
    {#if target.if_gone === 'start'}
      <div class="auto-fld">
        <Select
          label={t('automations.session.project')}
          data-session-project
          value={target.project_id == null ? '' : String(target.project_id)}
          onchange={(e) => set('project_id', e.currentTarget.value === '' ? null : Number(e.currentTarget.value))}
        >
          {#snippet children()}
            <option value="" disabled>{t('automations.session.pick_project')}</option>
            {#each projects as project (project.id)}
              {#if project.id !== null}<option value={String(project.id)}>{project.name}</option>{/if}
            {/each}
          {/snippet}
        </Select>
      </div>
    {/if}
  </div>
  <p class="auto-form__note">{t('automations.session.note')}</p>
{/if}
