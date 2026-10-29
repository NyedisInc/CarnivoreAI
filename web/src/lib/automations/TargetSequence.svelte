
<script lang="ts">
  import Card from '../base/Card.svelte';
  import type { AutomationTarget, ProjectChoice, Targets } from './api';
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import Select from '../base/Select.svelte';
  import { codeWords } from './logic/words';
  import { SEQUENCE_MAX_STEPS, SEQUENCE_MIN_STEPS, sequenceKinds, TARGET_FORMS } from './target-forms';

  let { target = $bindable(), targets, projects }: { target: AutomationTarget; targets: Targets; projects: ProjectChoice[] } = $props();

  const steps = $derived((target.steps as AutomationTarget[]) ?? []);

  function pick(index: number, kind: string): void {
    const blank = TARGET_FORMS[kind]?.blank(targets);
    if (blank) target = { ...target, steps: steps.map((s, i) => (i === index ? blank : s)) };
  }

  function add(): void {
    const kind = sequenceKinds(targets, false)[0];
    const blank = kind ? TARGET_FORMS[kind]?.blank(targets) : null;
    if (blank) target = { ...target, steps: [...steps.slice(0, -1), blank, steps[steps.length - 1]] };
  }

  function remove(index: number): void {
    target = { ...target, steps: steps.filter((_, i) => i !== index) };
  }
</script>

<ol class="auto-steps" data-sequence-steps>
  {#each steps as step, index (index)}
    {@const kinds = sequenceKinds(targets, index === steps.length - 1)}
    {@const Form = TARGET_FORMS[step.kind]?.component}
    <li class="auto-step" data-sequence-step={String(index)}>
      <Card title={t('automations.sequence.step', { n: index + 1 })} compact headingLevel={4}>
        {#snippet actions()}
          <Select
            size="sm"
            data-step-kind
            aria-label={t('automations.field.target')}
            value={step.kind}
            options={kinds.map((kind) => ({ value: kind, label: codeWords('automations.target', kind) }))}
            onchange={(e) => pick(index, e.currentTarget.value)}
          />
          <Button
            variant="quiet"
            size="sm"
            data-step-remove
            disabled={steps.length <= SEQUENCE_MIN_STEPS}
            aria-label={t('automations.sequence.remove_aria', { n: index + 1 })}
            onclick={() => remove(index)}>{t('automations.sequence.remove')}</Button
          >
        {/snippet}
        {#snippet children()}
          {#if Form}<Form bind:target={(target.steps as AutomationTarget[])[index]} {targets} {projects} />{/if}
        {/snippet}
      </Card>
    </li>
  {/each}
</ol>
<div class="auto-form__row">
  <Button size="sm" data-step-add disabled={steps.length >= SEQUENCE_MAX_STEPS} onclick={add}>
    {t('automations.sequence.add')}
  </Button>
  <span class="auto-form__note">{t('automations.sequence.note')}</span>
</div>
