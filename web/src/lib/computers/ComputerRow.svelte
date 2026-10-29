<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import PackMarks from '../pack-machines/PackMarks.svelte';
  import PackMeter from '../pack-machines/PackMeter.svelte';
  import { linkMarkFor, linkStateOf, loadPercent } from '../pack-machines/pack-meter-math';
  import { makeMaster, packActivity } from '../pack-machines/pack-machines-store.svelte';
  import type { ComputerEntry } from './computers-api';
  import { remove, setDirection } from './computers-store.svelte';
  import { ageWords, dialWords } from './computers-format';
  import ComputerUpdate from './ComputerUpdate.svelte';

  const TOOLS = ['python3.12', 'python3', 'node', 'npm', 'git', 'gh', 'docker', 'tmux', 'claude', 'playwright', 'playwright_browsers'] as const;

  interface Props {
    computer?: ComputerEntry | null;
    machine?: import('../pack-machines/pack-machines-store.svelte').PackMachine | null;
    nowMs: number;
    busy: boolean;
  }
  const { computer = null, machine = null, nowMs, busy }: Props = $props();

  let confirming = $state(false);
  const id = $derived(machine?.install_id ?? computer?.install_id ?? '');
  const label = $derived(machine?.label || computer?.label || id.slice(0, 8));
  const isSelf = $derived(machine?.is_self === true);
  const oneWay = $derived(computer?.direction === 'one_way');
  const dialNote = $derived(computer ? dialWords(computer) : null);
  const stateWord = $derived(machine ? t(`pack.machines.state.${machine.state}`) : '');
  const link = $derived(isSelf ? null : (machine ? linkMarkFor(machine) : linkStateOf(computer?.state ?? '')));
  const snap = $derived(machine?.snapshot ?? null);
  const specs = $derived(machine?.specs ?? null);
  const figure = (value: number | null | undefined, unit = ''): string => (value === null || value === undefined ? '-' : `${Math.round(value)}${unit}`);
</script>

<li class="cmp-row" data-computer={id} data-direction={computer?.direction ?? 'both'} data-master={machine?.is_master === true} data-machine={id}>
  <div class="cmp-head">
    <span class="cmp-name">{label}</span>
    <PackMarks alpha={machine?.is_master === true} self={isSelf} {link} />
    {#if computer}
      <span class="cmp-fp" data-cmp="fid">{computer.fid_short}</span>
      {#if computer.transport === 'ssh'}<span class="cmp-state" data-cmp="transport">{t('computers.row.over_ssh')}</span>{/if}
    {/if}
    {#if !isSelf && machine?.paired && !machine.is_master}
      <button type="button" class="modal-btn modal-btn-secondary pk-act" disabled={packActivity.busy !== null}
        onclick={() => void makeMaster(machine.install_id)} data-pm="make-master">{t('pack.machines.make_master')}</button>
    {/if}
    {#if computer && !confirming}
      <button type="button" class="modal-btn modal-btn-danger pk-act" data-cmp="remove" disabled={busy} onclick={() => (confirming = true)}>
        {t('computers.row.remove')}
      </button>
    {/if}
  </div>
  {#if machine && !computer && stateWord && machine.state !== 'self' && machine.state !== 'connected'}<p class="cmp-note" data-pm="state-word">{stateWord}</p>{/if}
  {#if specs}
    <p class="cmp-meta" data-pm="specs">{specs.model ?? ''} {figure(specs.cores)} {t('pack.machines.cores')} {figure(specs.mem_total_gb)} gb</p>
  {/if}
  {#if snap}
    <div class="pk-meters" data-pm="stats">
      <PackMeter label={t('pack.machines.cpu')} pct={loadPercent(snap.load.load_1, snap.load.cores)}
        text={`${figure(snap.load.load_1)}/${figure(snap.load.cores)}`} reservePct={snap.reserve.cpu_pct}
        title={t('pack.meter.cpu_title', { load: figure(snap.load.load_1), cores: figure(snap.load.cores), reserve: snap.reserve.cpu_pct })} />
      <PackMeter label={t('pack.machines.mem')} pct={snap.load.memory_percent ?? null} text={figure(snap.load.memory_percent, '%')}
        reservePct={snap.reserve.mem_pct}
        title={t('pack.meter.mem_title', { used: figure(snap.load.memory_percent), reserve: snap.reserve.mem_pct })} />
      <PackMeter label={t('pack.machines.disk')} pct={snap.load.disk_percent ?? null} text={figure(snap.load.disk_percent, '%')}
        title={t('pack.meter.disk_title', { used: figure(snap.load.disk_percent) })} />
      <p class="cmp-meta" data-pm="reserve-level">{t('pack.machines.reserve')} {t(`pack.machines.level.${snap.reserve.level}`)}
        {snap.reserve.cpu_pct}% / {snap.reserve.mem_pct}%</p>
    </div>
  {/if}
  {#if snap?.toolchain}
    <p class="pm-tools" data-pm="toolchain">
      <span class="pl-label">{t('pack.machines.tools')}</span>
      {#each TOOLS as tool (tool)}
        {#if tool in snap.toolchain}
          <span class="pm-tool" data-tool={tool} data-on={snap.toolchain[tool] === true}>{t(`pack.machines.tool.${tool}`)}</span>
        {/if}
      {/each}
    </p>
  {/if}
  {#if isSelf || computer?.host_key}<ComputerUpdate hostKey={isSelf ? '' : (computer?.host_key ?? '')} />{/if}
  {#if computer}
    {#if dialNote}<p class="cmp-note" role="status" data-cmp="dial" data-dial={computer.dial?.state}>{dialNote}</p>{/if}
    {#if computer.possible_duplicate_of !== null}
      <p class="cmp-note" data-cmp="duplicate">{t('computers.row.duplicate')}</p>
    {/if}
    <div class="cmp-head">
      <Check label={t('computers.row.control', { label: computer.label })} checked={!oneWay} role="switch" disabled={busy}
        data-cmp="direction" onToggle={(next) => void setDirection(computer.install_id, next)} />
      <span class="cmp-meta" data-cmp="last-seen">{t('computers.row.last_seen', { age: ageWords(computer.last_link_at, nowMs) })}</span>
    </div>
    {#if oneWay}<p class="cmp-note" data-cmp="one-way">{t('computers.row.one_way_note', { label: computer.label })}</p>{/if}
    {#if confirming}
      <div class="cmp-confirm" data-cmp="remove-confirm">
        <p class="cmp-note">{t('computers.row.remove_confirm', { label: computer.label })}</p>
        <div class="cmp-actions">
          <button type="button" class="modal-btn modal-btn-secondary" onclick={() => (confirming = false)}>{t('computers.row.cancel')}</button>
          <button type="button" class="modal-btn modal-btn-danger" data-cmp="remove-yes" disabled={busy}
            onclick={() => void remove(computer.install_id, computer.label).then(() => (confirming = false))}>{t('computers.row.remove')}</button>
        </div>
      </div>
    {/if}
  {/if}
</li>
