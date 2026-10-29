<script lang="ts">
  import './pack-machines.css';
  import './pack-work.css';
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import MachineEditor from './MachineEditor.svelte';
  import PackMarks from './PackMarks.svelte';
  import type { PackMachine, Restrictions } from './pack-machines-store.svelte';

  interface Props {
    machine: PackMachine;
  }
  const { machine }: Props = $props();

  const RULES: readonly (keyof Restrictions)[] = ['may_host_agents', 'may_receive_projects', 'may_install_tools', 'may_receive_credentials', 'may_update_carnivore'];
  const snap = $derived(machine.snapshot);
  const cfg = $derived(snap?.reserve.config);
  const rules = $derived(RULES.filter((rule) => !(machine.is_self && rule === 'may_receive_credentials')));
  let open = $state(false);
</script>

{#if snap}
  <li class="pw-machine" data-machine={machine.install_id}>
    <div class="pm-head">
      <span class="pm-name">{machine.label || machine.install_id.slice(0, 8)}</span>
      <PackMarks alpha={machine.is_master} self={machine.is_self} />
      <span class="pm-state" data-state={machine.state}>{t(`pack.machines.state.${machine.state}`)}</span>
      <Button size="sm" data-pw-edit aria-expanded={open} onclick={() => (open = !open)}>
        {open ? t('pack.machines.close') : t('pack.machines.edit')}</Button>
    </div>
    <div class="pw-chips" data-pw="reserve-chips">
      <span class="pw-chip pw-chip--now">{t('pack.work.chip.now', { level: t(`pack.machines.level.${snap.reserve.level}`), cpu: snap.reserve.cpu_pct, mem: snap.reserve.mem_pct })}</span>
      {#if cfg}
        <span class="pw-chip">{t('pack.work.chip.level', { level: t('pack.machines.level.in_use'), cpu: cfg.in_use.cpu_pct, mem: cfg.in_use.mem_pct })}</span>
        <span class="pw-chip">{t('pack.work.chip.level', { level: t('pack.machines.level.away'), cpu: cfg.away.cpu_pct, mem: cfg.away.mem_pct })}</span>
      {/if}
    </div>
    <div class="pw-chips" data-pw="rule-chips">
      {#each rules as rule (rule)}
        <span class="pw-chip" data-on={snap.restrictions[rule] === true}>{t(`pack.machines.rule.${rule}`)}</span>
      {/each}
      {#if snap.restrictions.max_agents != null}
        <span class="pw-chip">{t('pack.work.chip.cap', { n: snap.restrictions.max_agents })}</span>
      {/if}
    </div>
    {#if open}<MachineEditor {machine} />{/if}
  </li>
{/if}
