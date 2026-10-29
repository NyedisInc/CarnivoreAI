<script lang="ts">
  import './pack-machines.css';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import NumberField from '../base/NumberField.svelte';
  import ReserveForm from './ReserveForm.svelte';
  import { saveRestrictions, type PackMachine, type Restrictions } from './pack-machines-store.svelte';

  interface Props {
    machine: PackMachine;
  }
  const { machine }: Props = $props();

  const RULES: readonly (keyof Restrictions)[] = ['may_host_agents', 'may_receive_projects', 'may_install_tools', 'may_receive_credentials', 'may_update_carnivore'];
  const snap = $derived(machine.snapshot);
  const rules = $derived(RULES.filter((rule) => !(machine.is_self && rule === 'may_receive_credentials')));

  function setCap(value: number | null): void {
    if (value === null) return void saveRestrictions(machine.install_id, { max_agents: null });
    if (Number.isInteger(value) && value >= 0 && value <= 10000) void saveRestrictions(machine.install_id, { max_agents: value });
  }

  function ruleLocked(on: boolean): boolean {
    return !machine.is_self && !on;
  }
</script>

{#if snap}
  {@const cfg = snap.reserve.config}
  <div class="pm-edit" data-pm="editor">
    {#if cfg}
      {#key JSON.stringify(cfg)}
        <ReserveForm {machine} reserve={{ ...snap.reserve, config: cfg }} />
      {/key}
    {/if}
    <h3 class="pl-label">{t('pack.machines.restrictions_title')}</h3>
    <p class="pm-note">{machine.is_self ? t('pack.machines.restrictions_own') : t('pack.machines.restrictions_peer')}</p>
    <div class="pm-rules">
      {#each rules as rule (rule)}
        {@const on = snap.restrictions[rule] === true}
        <Check label={t(`pack.machines.rule.${rule}`)} checked={on} disabled={ruleLocked(on)} data-rule={rule}
          onToggle={(next) => void saveRestrictions(machine.install_id, { [rule]: next })} />
      {/each}
    </div>
    <NumberField label={t('pack.machines.max_agents')} min={0} max={10000} placeholder={t('pack.machines.no_cap')}
      value={snap.restrictions.max_agents ?? null} onchange={setCap} />
  </div>
{/if}
