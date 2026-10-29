
<script lang="ts">
  import { onMount } from 'svelte';
  import Field from '../base/Field.svelte';
  import NumberField from '../base/NumberField.svelte';
  import OptionList, { type OptionItem } from '../base/OptionList.svelte';
  import Select from '../base/Select.svelte';
  import State from '../base/State.svelte';
  import { t } from '../i18n/index.svelte';
  import type { AccountChoice, AutomationTarget, ProjectChoice } from './api';
  import { listAnthropicKeys, listClaudeLogins, listProjectChoices } from './api';
  import { EFFORTS, LEVELS, UNATTENDED_PHRASE, toolsFor, type Level } from './agent-defaults';
  import FieldHint from './schedule/FieldHint.svelte';

  let { target = $bindable(), part = 'all' }: { target: AutomationTarget; part?: 'all' | 'lead' | 'rest' } = $props();

  let projects = $state<ProjectChoice[] | null>(null);
  let logins = $state<AccountChoice[]>([]);
  let keys = $state<AccountChoice[]>([]);
  let failed = $state(false);

  const level = $derived((target.permission as Level) ?? 'read_only');
  const unattended = $derived(level === 'unattended');
  const levelOptions: OptionItem[] = LEVELS.map((option) => ({
    value: option,
    label: t(`automations.agent.level.${option}`),
    reason: t(`automations.agent.level.${option}_note`),
  }));
  const phrase = $derived(String(target.acknowledge_unattended ?? ''));
  const minutes = $derived(Math.round(Number(target.timeout_s ?? 1800) / 60));
  const folders = $derived(
    projects && target.folder && !projects.some((p) => p.folder === target.folder)
      ? [{ name: String(target.folder), folder: String(target.folder) }, ...projects]
      : (projects ?? []),
  );

  onMount(async () => {
    if (part === 'lead') return;
    try {
      [projects, logins, keys] = await Promise.all([listProjectChoices(), listClaudeLogins(), listAnthropicKeys()]);
    } catch {
      failed = true;
      projects = projects ?? [];
    }
  });

  function grow(value: () => string): (node: HTMLElement) => () => void {
    return (node) => {
      void value();
      const fit = (): void => {
        node.style.height = 'auto';
        node.style.height = `${node.scrollHeight + node.offsetHeight - node.clientHeight}px`;
      };
      fit();
      node.addEventListener('input', fit);
      return () => node.removeEventListener('input', fit);
    };
  }

  function set(field: string, value: unknown): void {
    target = { ...target, [field]: value };
  }

  function setOptional(field: string, value: string): void {
    const { [field]: _drop, ...rest } = target;
    target = (value.trim() === '' ? rest : { ...rest, [field]: value.trim() }) as AutomationTarget;
  }

  function pickLevel(next: Level): void {
    const { acknowledge_unattended: _drop, ...rest } = target;
    target = { ...rest, permission: next, tools: toolsFor(next) };
  }

  function setNumber(field: string, raw: string, low: number, high: number): void {
    const n = Number(raw);
    if (Number.isFinite(n)) set(field, Math.min(high, Math.max(low, n)));
  }
</script>

{#if part !== 'rest'}
  <Field
    label={t('automations.simple.hint.kind.agent.label')}
    multiline
    rows={1}
    data-agent-prompt
    maxlength={32768}
    placeholder={t('automations.simple.hint.kind.agent.eg')}
    {@attach grow(() => String(target.prompt ?? ''))}
    value={String(target.prompt ?? '')}
    oninput={(e) => set('prompt', e.currentTarget.value)}
  />
{/if}

{#if part !== 'lead'}
{#if projects === null}
  <p class="auto-form__note" role="status">{t('automations.agent.loading')}</p>
{:else}
  {#if failed}<State kind="error" inline title={t('automations.agent.unavailable')} />{/if}
  <div class="auto-fld">
    <Select label={t('automations.agent.folder')} data-agent-folder value={String(target.folder ?? '')} onchange={(e) => set('folder', e.currentTarget.value)}>
      {#snippet children()}
        <option value="" disabled>{t('automations.agent.folder_pick')}</option>
        {#each folders as project (project.folder)}
          <option value={project.folder}>{project.name}</option>
        {/each}
      {/snippet}
    </Select>
    {#if target.folder}<pre class="r-pre ap-cmd-full" data-folder-full>{target.folder}</pre>{/if}
    <FieldHint field="folder" text={t('automations.agent.folder_note')} eg={projects[0]?.folder ?? t('automations.simple.hint.folder_eg')} onFill={(eg) => set('folder', eg)} />
  </div>
  <div data-agent-levels>
    <OptionList
      prompt={t('automations.agent.permission')}
      options={levelOptions}
      value={level}
      onValueChange={(next) => pickLevel(next as Level)}
    />
  </div>
  {#if unattended}
    <State kind="error" role="alert" data-agent-warning title={t('automations.agent.unattended_warning')}>
      {#snippet actions()}
        <Field
          label={t('automations.agent.unattended_type', { phrase: UNATTENDED_PHRASE })}
          data-agent-phrase
          autocomplete="off"
          spellcheck={false}
          value={phrase}
          oninput={(e) => set('acknowledge_unattended', e.currentTarget.value)}
        />
      {/snippet}
    </State>
  {/if}

  <div class="auto-fld">
    <Field
      label={t('automations.agent.tools')}
      data-agent-tools
      spellcheck={false}
      placeholder={toolsFor('read_only').slice(0, 3).join(', ')}
      value={((target.tools as string[]) ?? []).join(', ')}
      onchange={(e) => set('tools', e.currentTarget.value.split(',').map((x) => x.trim()).filter(Boolean))}
    />
    <FieldHint field="tools" text={t('automations.agent.tools_note')} eg={toolsFor('read_only').slice(0, 3).join(', ')} onFill={(eg) => set('tools', eg.split(',').map((x) => x.trim()))} />
  </div>

  <div class="auto-form__row">
    <div class="auto-fld">
      <Select label={t('automations.agent.login')} data-agent-login value={String(target.login_account_id ?? '')} onchange={(e) => setOptional('login_account_id', e.currentTarget.value)}>
        {#snippet children()}
          <option value="">{t('automations.agent.login_default')}</option>
          {#each logins as login (login.id)}<option value={login.id}>{login.name}</option>{/each}
        {/snippet}
      </Select>
      <FieldHint field="login" text={t('automations.simple.hint.login')} eg={t('automations.agent.login_default')} onFill={() => setOptional('login_account_id', '')} />
    </div>
    <div class="auto-fld">
      <Select label={t('automations.agent.api_key')} data-agent-key value={String(target.api_key_connection_id ?? '')} onchange={(e) => setOptional('api_key_connection_id', e.currentTarget.value)}>
        {#snippet children()}
          <option value="">{t('automations.agent.api_key_none')}</option>
          {#each keys as key (key.id)}<option value={key.id}>{key.name}</option>{/each}
        {/snippet}
      </Select>
      <FieldHint field="api_key" text={t('automations.agent.login_note')} eg={t('automations.agent.api_key_none')} onFill={() => setOptional('api_key_connection_id', '')} />
    </div>
  </div>

  <div class="auto-form__row">
    <div class="auto-fld">
      <Field
        label={t('automations.simple.agent.model')}
        data-agent-model
        autocomplete="off"
        spellcheck={false}
        placeholder={t('automations.simple.agent.model_placeholder')}
        value={String(target.model ?? '')}
        onchange={(e) => setOptional('model', e.currentTarget.value)}
      />
      <FieldHint field="model" text={t('automations.simple.agent.model_hint')} eg={t('automations.simple.hint.model_eg')} onFill={(eg) => setOptional('model', eg)} />
    </div>
    <div class="auto-fld">
      <Select label={t('automations.simple.agent.effort')} data-agent-effort value={String(target.effort ?? '')} onchange={(e) => setOptional('effort', e.currentTarget.value)}>
        {#snippet children()}
          <option value="">{t('automations.simple.agent.effort_default')}</option>
          {#each EFFORTS as level (level)}<option value={level}>{t(`automations.simple.agent.effort.${level}`)}</option>{/each}
        {/snippet}
      </Select>
      <FieldHint field="effort" text={t('automations.simple.hint.effort')} eg={t('automations.simple.hint.effort_eg')} onFill={(eg) => setOptional('effort', eg)} />
    </div>
  </div>

  <div class="auto-form__row">
    <div class="auto-fld">
      <NumberField label={t('automations.agent.budget')} min={0.05} max={50} step={0.05} data-agent-budget value={Number(target.max_budget_usd ?? 1)} onchange={(v) => setNumber('max_budget_usd', String(v ?? ''), 0.05, 50)} />
      <FieldHint field="budget" text={t('automations.simple.hint.budget')} eg={t('automations.simple.hint.budget_eg')} onFill={(eg) => setNumber('max_budget_usd', eg, 0.05, 50)} />
    </div>
    <div class="auto-fld">
      <NumberField label={t('automations.agent.turns')} min={1} max={200} step={1} data-agent-turns value={Number(target.max_turns ?? 30)} onchange={(v) => setNumber('max_turns', String(v ?? ''), 1, 200)} />
      <FieldHint field="turns" text={t('automations.simple.hint.turns')} eg={t('automations.simple.hint.turns_eg')} onFill={(eg) => setNumber('max_turns', eg, 1, 200)} />
    </div>
    <div class="auto-fld">
      <NumberField label={t('automations.agent.minutes')} min={1} max={60} step={1} data-agent-minutes value={minutes} onchange={(v) => setNumber('timeout_s', String(Number(v) * 60), 60, 3600)} />
      <FieldHint field="minutes" text={t('automations.simple.hint.minutes')} eg={t('automations.simple.hint.minutes_eg')} onFill={(eg) => setNumber('timeout_s', String(Number(eg) * 60), 60, 3600)} />
    </div>
  </div>
{/if}
{/if}
