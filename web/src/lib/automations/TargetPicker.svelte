
<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { AutomationTarget, ProjectChoice, Targets } from './api';
  import { t } from '../i18n/index.svelte';
  import Select from '../base/Select.svelte';
  import { codeLabel } from './format';
  import { offeredKinds, TARGET_FORMS } from './target-forms';

  let {
    target = $bindable(),
    targets,
    projects = [],
    part = 'all',
    hint,
  }: { target: AutomationTarget | null; targets: Targets; projects?: ProjectChoice[]; part?: 'all' | 'kind' | 'lead' | 'rest'; hint?: Snippet } = $props();

  const kinds = $derived(offeredKinds(targets));
  const form = $derived(target ? TARGET_FORMS[target.kind] : undefined);
  const Form = $derived(form?.component);
  const inLead = $derived(target?.kind === 'agent' || target?.kind === 'recipe');
  const formPart = $derived(target?.kind === 'agent' && part !== 'all' ? { part } : {});

  function pick(kind: string): void {
    target = TARGET_FORMS[kind]?.blank(targets) ?? null;
  }
</script>

{#if kinds.length === 0 && !target}
  {#if part !== 'lead'}<p class="auto-form__note" role="status">{t('automations.target.none')}</p>{/if}
{:else}
  {#if part === 'all' || part === 'kind'}
    <div class="auto-fld">
      {#if form}
        <Select
          label={t('automations.field.target')}
          data-target-kind
          value={target?.kind ?? ''}
          options={kinds.map((kind) => ({ value: kind, label: codeLabel('automations.target', kind) }))}
          onchange={(e) => pick(e.currentTarget.value)}
        />
      {:else}
        <span class="oc-label">{t('automations.field.target')}</span>
        <span class="auto-form__fixed" data-target-fixed>{target ? codeLabel('automations.target', target.kind) : ''}</span>
      {/if}
      {#if part === 'kind'}{@render hint?.()}{/if}
    </div>
  {/if}
  {#if target && Form}
    {#if part === 'all' || (part === 'lead' && inLead) || (part === 'rest' && target.kind !== 'recipe')}
      <Form bind:target {targets} {projects} {...formPart} />
    {/if}
  {:else if target && part !== 'kind' && part !== 'lead'}
    <p class="auto-form__note">{t('automations.editor.no_form')}</p>
  {/if}
{/if}
