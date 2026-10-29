
<script lang="ts">
  import type { AutomationTarget, Targets } from './api';
  import { t } from '../i18n/index.svelte';
  import Field from '../base/Field.svelte';
  import Select from '../base/Select.svelte';
  import { codeWords } from './logic/words';

  let { target = $bindable(), targets }: { target: AutomationTarget; targets: Targets } = $props();
  const recipes = $derived(targets.recipes);

  const current = $derived(recipes.find((r) => r.recipe === target.recipe) ?? recipes[0]);
  const reports = $derived(recipes.filter((r) => !r.system_action));
  const actions = $derived(recipes.filter((r) => r.system_action));
  const fields = $derived(
    Object.entries(current?.params_schema.properties ?? {}).filter(([, spec]) => ['integer', 'number', 'string'].includes(spec.type ?? '')),
  );
  const params = $derived((target.params ?? {}) as Record<string, number | string>);

  function pick(name: string): void {
    const spec = recipes.find((r) => r.recipe === name);
    const next: Record<string, unknown> = {};
    for (const [key, field] of Object.entries(spec?.params_schema.properties ?? {})) if (field.default !== undefined) next[key] = field.default;
    target = { kind: 'recipe', recipe: name, params: next };
  }

  function setParam(key: string, raw: string, kind: string | undefined): void {
    target = { ...target, params: { ...params, [key]: kind === 'string' ? raw : Number(raw) } };
  }
</script>

<div class="auto-form__row">
  <div class="auto-fld">
    <Select label={t('automations.recipe.field')} data-recipe-select value={target.recipe as string} onchange={(e) => pick(e.currentTarget.value)}>
      {#snippet children()}
        {#if reports.length}
          <optgroup label={t('automations.recipe.group_reports')}>
            {#each reports as recipe (recipe.recipe)}
              <option value={recipe.recipe}>{codeWords('automations.recipe', `${recipe.recipe}.label`)}</option>
            {/each}
          </optgroup>
        {/if}
        {#if actions.length}
          <optgroup label={t('automations.recipe.group_actions')}>
            {#each actions as recipe (recipe.recipe)}
              <option value={recipe.recipe}>{codeWords('automations.recipe', `${recipe.recipe}.label`)}</option>
            {/each}
          </optgroup>
        {/if}
      {/snippet}
    </Select>
  </div>
  {#each fields as [key, spec] (key)}
    <div class="auto-fld">
      <Field
        label={codeWords('automations.param', key)}
        type={spec.type === 'string' ? 'text' : 'number'}
        data-recipe-param={key}
        min={spec.minimum}
        max={spec.maximum}
        maxlength={spec.maxLength}
        value={String(params[key] ?? '')}
        oninput={(e) => setParam(key, e.currentTarget.value, spec.type)}
      />
    </div>
  {/each}
</div>
{#if current}<p class="auto-form__note">{codeWords('automations.recipe', `${current.recipe}.description`)}</p>{/if}
