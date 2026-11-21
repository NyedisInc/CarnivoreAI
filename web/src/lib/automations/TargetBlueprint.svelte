
<script lang="ts">
  import { onMount } from 'svelte';
  import { listBlueprints } from '../blueprints/api';
  import type { Blueprint } from '../blueprints/types';
  import type { AutomationTarget } from './api';
  import { t } from '../i18n/index.svelte';
  import State from '../base/State.svelte';
  import Checkbox from '../base/Checkbox.svelte';
  import Select from '../base/Select.svelte';
  import Segmented from '../base/Segmented.svelte';
  import { refusalCode, refusalText } from './format';
  import { placementApi, type Placement, type PlacementApi } from './placement-api';

  let { target = $bindable(), automationId, api: injected }: { target: AutomationTarget; automationId?: string; api?: PlacementApi } = $props();
  // svelte-ignore state_referenced_locally
  const placements: PlacementApi = injected ?? placementApi;

  let placement = $state<Placement>('here');
  let applies = $state(false);
  let placementProblem = $state('');

  let blueprints = $state<Blueprint[] | null>(null);
  let failed = $state(false);

  const current = $derived(blueprints?.find((b) => b.blueprint_uuid === target.blueprint_uuid));
  const picked = $derived(new Set((target.members as number[] | null) ?? current?.spec.sessions.map((_, i) => i) ?? []));

  const placeable = $derived(
    (current?.spec.sessions ?? []).some((member, i) => picked.has(i) && !(member as { host_key?: string | null }).host_key),
  );

  onMount(async () => {
    if (automationId) {
      try {
        const answer = await placements.read(automationId);
        placement = answer.placement;
        applies = answer.applies;
      } catch {
        applies = false;
      }
    }
    try {
      const list = await listBlueprints();
      blueprints = list.status === 'ok' ? list.blueprints : [];
      failed = list.status !== 'ok';
    } catch {
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

  async function choose(next: string): Promise<void> {
    if (!automationId || (next !== 'here' && next !== 'auto')) return;
    const before = placement;
    placement = next;
    placementProblem = '';
    try {
      placement = (await placements.write(automationId, next)).placement;
    } catch (error) {
      placement = before;
      placementProblem = refusalCode(error) === 'placement_unsupported' ? t('automations.placement.unsupported') : refusalText(error);
    }
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
    {#if automationId && applies && placeable}
      <div>
      <Segmented
        label={t('automations.placement.label')}
        data-automation-placement
        value={placement}
        onchange={(v) => void choose(v)}
        options={[
          { value: 'here', label: t('automations.placement.here'), attrs: { 'data-automation-placement-option': 'here' } },
          { value: 'auto', label: t('automations.placement.auto'), attrs: { 'data-automation-placement-option': 'auto' } },
        ]}
      />
      </div>
      <p class="auto-form__note">{t('automations.placement.note')}</p>
      {#if placementProblem}<State kind="error" inline title={placementProblem} data-automation-placement-problem />{/if}
    {/if}
  {/if}
{/if}
