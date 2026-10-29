
<script lang="ts">
  import { onMount } from 'svelte';
  import { listBlueprints } from '../blueprints/api';
  import type { Blueprint } from '../blueprints/types';
  import type { AutomationTarget } from './api';
  import { t } from '../i18n/index.svelte';
  import State from '../base/State.svelte';
  import Checkbox from '../base/Checkbox.svelte';
  import Select from '../base/Select.svelte';

  let { target = $bindable() }: { target: AutomationTarget } = $props();

  let blueprints = $state<Blueprint[] | null>(null);
  let failed = $state(false);

  const current = $derived(blueprints?.find((b) => b.blueprint_uuid === target.blueprint_uuid));
  const picked = $derived(new Set((target.members as number[] | null) ?? current?.spec.sessions.map((_, i) => i) ?? []));

  onMount(async () => {
    try {
      const list = await listBlueprints();
      blueprints = list.status === 'ok' ? list.blueprints : [];
      failed = list.status !== 'ok';
    } catch {
      // could not
      failed = true;
      blueprints = [];
      return;
    }
  });

  $effect(() => {
    const first = blueprints?.[0];
    if (first && !target.blueprint_uuid) target = { ...target, blueprint_uuid: first.blueprint_uuid, members: null };
  });

  function pick(uuid: string): void {
    target = { kind: 'blueprint_launch', blueprint_uuid: uuid, members: null };
  }

  function toggle(index: number, on: boolean): void {
    const total = current?.spec.sessions.length ?? 0;
    const next = new Set(picked);
    if (on) next.add(index);
    else next.delete(index);
    target = { ...target, members: next.size === total ? null : [...next].sort((a, b) => a - b) };
  }
</script>

{#if blueprints === null}
  <p class="auto-form__note" role="status">{t('automations.blueprint.loading')}</p>
{:else if failed}
  <State kind="error" inline title={t('automations.blueprint.unavailable')} />
{:else if blueprints.length === 0}
  <p class="auto-form__note" role="status">{t('automations.blueprint.none')}</p>
{:else}
  <Select
    label={t('automations.blueprint.field')}
    data-blueprint-select
    value={target.blueprint_uuid as string}
    options={blueprints.map((blueprint) => ({ value: blueprint.blueprint_uuid, label: blueprint.name }))}
    onchange={(e) => pick(e.currentTarget.value)}
  />
  {#if current}
    <fieldset class="auto-form__row" data-blueprint-members>
      <legend class="oc-label">{t('automations.blueprint.members')}</legend>
      {#each current.spec.sessions as member, index (index)}
        <Checkbox label={member.label} bind:checked={() => picked.has(index), (next) => toggle(index, next)} data-blueprint-member={String(index)} />
      {/each}
    </fieldset>
    <p class="auto-form__note">{t('automations.blueprint.note')}</p>
  {/if}
{/if}
