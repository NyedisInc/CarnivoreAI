
<script lang="ts">
  import type { AutomationTarget, ProjectChoice, Targets } from './api';
  import { t } from '../i18n/index.svelte';
  import Select from '../base/Select.svelte';
  import State from '../base/State.svelte';

  let { target = $bindable(), targets, projects }: { target: AutomationTarget; targets: Targets; projects: ProjectChoice[] } = $props();

  const commands = $derived(targets.commands);
  const missing = $derived(Boolean(target.command) && !commands.includes(target.command as string));
</script>

{#if commands.length === 0}
  <p class="auto-form__note" role="status" data-command-none>{t('automations.command.none')}</p>
{:else}
  <Select label={t('automations.command.field')} data-command-select value={(target.command as string) ?? ''} onchange={(e) => (target = { ...target, command: e.currentTarget.value })}>
    {#snippet children()}
      <option value="" disabled>{t('automations.command.pick')}</option>
      {#each commands as command (command)}<option value={command}>{command}</option>{/each}
    {/snippet}
  </Select>
  {#if target.command}<pre class="r-pre ap-cmd-full" data-command-full>{target.command}</pre>{/if}
{/if}
{#if missing}<State kind="error" inline title={t('automations.command.removed')} />{/if}
<Select
  label={t('automations.command.project')}
  data-command-project
  value={target.project_id == null ? '' : String(target.project_id)}
  onchange={(e) => (target = { ...target, project_id: e.currentTarget.value === '' ? null : Number(e.currentTarget.value) })}
>
  {#snippet children()}
    <option value="">{t('automations.command.home')}</option>
    {#each projects as project (project.id)}
      {#if project.id !== null}<option value={String(project.id)}>{project.name}</option>{/if}
    {/each}
  {/snippet}
</Select>
<p class="auto-form__note">{t('automations.command.note')}</p>
