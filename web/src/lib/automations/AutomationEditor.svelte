
<script lang="ts">
  import { onMount, type Snippet } from 'svelte';
  import * as api from './api';
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import Card from '../base/Card.svelte';
  import Field from '../base/Field.svelte';
  import Select from '../base/Select.svelte';
  import State from '../base/State.svelte';
  import ContractFields from './ContractFields.svelte';
  import TargetPicker from './TargetPicker.svelte';
  import { offeredKinds, TARGET_FORMS } from './target-forms';
  import type { EditorStart } from './schedule-prefill';
  import { refusalCode, refusalText, toMinutes } from './format';
  import FieldHint from './schedule/FieldHint.svelte';
  import IdeasList from './schedule/IdeasList.svelte';
  import WhenField from './schedule/WhenField.svelte';
  import { parsePick } from './schedule/compose';
  import { ideaTarget, TEXT_FIELD, type Idea } from './schedule/ideas';
  import { createBlockedReason, type WordsOutcome } from './schedule/words-model';

  interface Props {
    automation: api.Automation | null;
    targets: api.Targets;
    projects: api.ProjectChoice[];
    onDone: (saved: api.Automation) => void;
    onCancel: () => void;
    seed?: (EditorStart & { cron?: string }) | null;
    onConflict?: () => void;
    header?: Snippet;
    onIdea?: () => void;
  }
  let { automation, targets, projects, onDone, onCancel, seed = null, onConflict, header, onIdea }: Props = $props();

  /*  svelte-ignore */
  const start = automation;
  /*  svelte-ignore */
  const prefill = start ? null : seed;
  const NEW_CRON = '0 9 * * 1-5';
  let name = $state(start?.name ?? prefill?.name ?? '');
  let cron = $state(start?.trigger.cron ?? prefill?.cron ?? NEW_CRON);
  const enabled = start?.enabled ?? true;
  const keepsDefault = Boolean(start && start.delivery.notify && !start.delivery.notify_on);
  let delivery = $state<string>(start ? (!start.delivery.notify ? 'none' : (start.delivery.notify_on ?? 'default')) : 'failure');
  let description = $state(start?.description ?? '');
  let projectId = $state<number | null>(start?.project_id ?? prefill?.projectId ?? null);
  let misfire = $state<api.Misfire>(start?.misfire ?? 'run_once');
  let retryMax = $state(start?.retry_max ?? 0);
  let backoffMin = $state<number | null>(toMinutes(start?.retry_backoff_s ?? 300));
  let runtimeMin = $state<number | null>(start?.max_runtime_s ? toMinutes(start.max_runtime_s) : null);
  // svelte-ignore state_referenced_locally
  let target = $state<api.AutomationTarget | null>(
    start
      ? structuredClone($state.snapshot(start.target))
      : prefill?.target
        ? structuredClone($state.snapshot(prefill.target))
        : (TARGET_FORMS[offeredKinds(targets)[0] ?? '']?.blank(targets) ?? null),
  );
  let pending = $state<WordsOutcome | null>(null);
  let busy = $state(false);
  let problem = $state('');
  let formEl = $state<HTMLFormElement | null>(null);

  const hasForm = $derived(target ? Boolean(TARGET_FORMS[target.kind]) : false);
  const blocked = $derived(createBlockedReason(pending));
  // svelte-ignore state_referenced_locally
  const initialMode = start ? (parsePick(cron) ? 'pick' : 'cron') : 'words';
  const canSave = $derived(
    !busy && blocked === null && name.trim() !== '' && cron.trim() !== '' && target !== null && (TARGET_FORMS[target.kind]?.ready?.(target) ?? true),
  );

  const ONE_LINE = ['recipe', 'agent', 'command', 'session_message', 'swarm_card'];
  const WRITTEN = ['agent', 'command', 'session_message', 'swarm_card'];
  const kindOneLine = $derived(target && ONE_LINE.includes(target.kind) ? `automations.simple.hint.kind_one.${target.kind}` : '');
  const kindWritten = $derived(target && WRITTEN.includes(target.kind) ? `automations.simple.hint.kind.${target.kind}` : '');

  function fillKind(): void {
    if (target?.kind !== 'agent' && offeredKinds(targets).includes('agent')) target = TARGET_FORMS.agent?.blank(targets) ?? target;
  }

  function fillKindText(eg: string): void {
    const field = TEXT_FIELD[target?.kind ?? ''];
    if (target && field) target = { ...target, [field]: eg };
  }

  function useIdea(idea: Idea): void {
    const filled = ideaTarget(idea.kind, t(`automations.simple.ideas.${idea.n}.text`), targets);
    if (!filled) return;
    name = t(`automations.simple.ideas.${idea.n}.name`);
    description = '';
    cron = idea.cron;
    pending = null;
    target = filled;
    onIdea?.();
    formEl?.scrollIntoView?.({ block: 'start' });
    formEl?.querySelector<HTMLInputElement>('[data-auto-field="name"]')?.focus({ preventScroll: true });
  }

  onMount(() => {
    formEl?.querySelector<HTMLInputElement>('[data-auto-field="name"]')?.focus({ preventScroll: true });
  });

  async function save(): Promise<void> {
    if (!canSave || !target) return;
    busy = true;
    problem = '';
    const chosen: api.Delivery = {
      notify: delivery !== 'none',
      notify_on: (['none', 'default'].includes(delivery) ? null : delivery) as api.Delivery['notify_on'],
    };
    try {
      const phrase = target.kind === 'agent' && target.permission === 'unattended' ? { acknowledge_unattended: String(target.acknowledge_unattended ?? '') } : {};
      const body = {
        name: name.trim(),
        cron: cron.trim(),
        delivery: chosen,
        enabled,
        ...phrase,
        description: description.trim(),
        project_id: projectId,
        misfire,
        retry_max: retryMax,
        retry_backoff_s: Math.round(backoffMin ?? 5) * 60,
        max_runtime_s: runtimeMin === null ? null : Math.round(runtimeMin) * 60,
      };
      const saved = automation
        ? await api.updateAutomation(automation.automation_id, automation.revision, hasForm ? { ...body, target } : body)
        : await api.createAutomation({ ...body, target });
      onDone(saved);
    } catch (error) {
      if (onConflict && refusalCode(error) === 'revision_conflict') onConflict();
      else problem = refusalText(error);
    } finally {
      busy = false;
    }
  }
</script>

<form
  bind:this={formEl}
  class="ap-pn-ed"
  data-automation-editor
  novalidate
  onsubmit={(e) => {
    e.preventDefault();
    void save();
  }}
>
  <Card title={automation ? t('automations.page.editor.edit', { name: automation.name }) : t('automations.page.editor.new')} compact>
    {#snippet children()}
      {@render header?.()}
      <div class="ap-pn-f">
        <Field
          label={t('automations.page.editor.name')}
          data-auto-field="name"
          maxlength={80}
          autocomplete="off"
          placeholder={t('automations.simple.hint.name_eg')}
          bind:value={name}
        />
        <FieldHint field="name" text={t('automations.simple.hint.name')} eg={t('automations.simple.hint.name_eg')} onFill={(eg) => (name = eg)} />
      </div>
      <TargetPicker part="kind" bind:target {targets} {projects}>
        {#snippet hint()}
          {#if kindOneLine}<FieldHint field="kind" text={t(kindOneLine)} eg={t('automations.target.agent')} onFill={fillKind} />{/if}
        {/snippet}
      </TargetPicker>
      <TargetPicker part="lead" bind:target {targets} {projects} />
      {#if kindWritten && target?.kind === 'agent'}<FieldHint field="text" text={t(`${kindWritten}.hint`)} eg={t(`${kindWritten}.eg`)} onFill={fillKindText} />{/if}
      <WhenField bind:cron bind:pending {initialMode} />
      <div class="ap-pn-f">
        <Select label={t('automations.page.editor.delivery')} data-auto-field="notify" bind:value={delivery}>
          {#snippet children()}
            {#if keepsDefault}<option value="default">{t('automations.notify_on.default')}</option>{/if}
            {#each ['none', 'failure', 'report', 'always'] as when (when)}
              <option value={when}>{t(`automations.page.editor.notify.${when}`)}</option>
            {/each}
          {/snippet}
        </Select>
        <FieldHint field="notify" text={t('automations.simple.hint.notify')} eg={t('automations.page.editor.notify.failure')} onFill={() => (delivery = 'failure')} />
      </div>
      <div class="ap-pn-f">
        <Field
          label={t('automations.page.editor.description')}
          data-auto-field="description"
          maxlength={500}
          autocomplete="off"
          placeholder={t('automations.simple.hint.description_eg')}
          bind:value={description}
        />
        <FieldHint field="description" text={t('automations.simple.hint.description')} eg={t('automations.simple.hint.description_eg')} onFill={(eg) => (description = eg)} />
      </div>
      
      <div class="ap-pn-edb" data-editor-target-block>
        <TargetPicker part="rest" bind:target {targets} {projects} />
        {#if kindWritten && target?.kind !== 'agent'}<FieldHint field="text" text={t(`${kindWritten}.hint`)} eg={t(`${kindWritten}.eg`)} onFill={fillKindText} />{/if}
        <ContractFields bind:projectId bind:misfire bind:retryMax bind:backoffMin bind:runtimeMin {projects} />
      </div>
      {#if blocked}<State kind="warn" inline title={blocked} data-editor-blocked />{/if}
      {#if problem}<State kind="error" inline title={problem} data-editor-problem />{/if}
    {/snippet}
    {#snippet foot()}
      <Button type="submit" variant="confirm" size="sm" data-editor-save disabled={!canSave}>
        {busy ? t('automations.editor.saving') : automation ? t('automations.page.editor.save') : t('automations.page.editor.create')}
      </Button>
      <Button size="sm" data-editor-cancel onclick={onCancel}>{t('automations.page.editor.cancel')}</Button>
    {/snippet}
  </Card>
</form>
{#if !automation}<IdeasList {targets} onUse={useIdea} />{/if}
