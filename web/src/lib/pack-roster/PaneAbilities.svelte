
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import Button from '../base/Button.svelte';
  import { ageWords } from '../computers/computers-format';
  import { packMachines, type CanBlock } from '../pack-machines/pack-machines-store.svelte';
  import { abilitiesApi, type AbilitiesApi } from './abilities-api';
  import LabelEditor from './LabelEditor.svelte';
  import { pressureLine } from './pressure-line';
  import type { RosterComputer } from './roster-model';

  const { c, onWork, nowMs, api = abilitiesApi }: { c: RosterComputer; onWork: () => void; nowMs: number; api?: AbilitiesApi } = $props();

  const snap = $derived(c.machine?.snapshot ?? null);
  let rescanned = $state<CanBlock | null>(null);
  let fresh = $state<boolean | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  const can = $derived(rescanned && rescanned.probed_at > (snap?.can?.probed_at ?? 0) ? rescanned : (snap?.can ?? null));
  const pressure = $derived(snap?.pressure ?? null);
  const tools = $derived(can ? Object.entries(can.tools).sort(([a], [b]) => a.localeCompare(b)) : []);
  const onOff = (on: boolean | undefined): string => t(on ? 'roster.can.on' : 'roster.can.off');
  const checked = $derived(fresh === false || !can ? t('roster.can.checked_recent') : t('roster.can.checked', { age: ageWords(new Date(can.probed_at * 1000).toISOString(), nowMs) }));

  async function checkAgain(): Promise<void> {
    if (busy) return;
    busy = true;
    error = null;
    try {
      const answer = await api.rescan(c.id);
      fresh = answer.fresh;
      if ('probed_at' in answer.can) rescanned = answer.can;
      await packMachines.refresh(true);
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('roster.can.failed'));
    } finally {
      busy = false;
    }
  }
</script>

{#if c.kind !== 'ssh-only' && c.machine}
  <section class="m1-sec" data-pm="abilities"><h3 class="pp-k">{t('roster.can.title')}</h3>
    {#if !can}
      <p class="pp-hint" data-pm="abilities-old">{t(snap ? 'roster.can.old' : 'roster.can.unknown')}</p>
    {:else}
      <dl class="pp-facts">
        <dt>{t('roster.can.os')}</dt><dd>{can.os}{can.os_version ? ` ${can.os_version}` : ''}</dd>
        <dt>{t('roster.can.chip')}</dt><dd>{[can.chip ?? can.arch, can.cores != null ? t('roster.card.cores', { n: can.cores }) : null].filter(Boolean).join(' · ') || '-'}</dd>
        <dt>{t('roster.ov.memory')}</dt><dd>{can.mem_gb != null ? t('roster.card.gb', { n: Math.round(can.mem_gb) }) : '-'}</dd>
        <dt>{t('roster.can.gpus')}</dt><dd>{can.gpus.length > 0 ? can.gpus.map((g) => (g.vram_gb != null ? `${g.model} ${t('roster.card.gb', { n: Math.round(g.vram_gb) })}` : g.model)).join(', ') : t('roster.can.none')}</dd>
        <dt>{t('roster.can.xcode')}</dt><dd>{can.xcode ? `${can.xcode}${can.ios_sim ? `, ${t('roster.can.ios_sim')}` : ''}` : t('roster.can.none')}</dd>
        <dt>{t('roster.can.brew')}</dt><dd>{onOff(can.brew)}</dd>
      </dl>
      <div class="pp-tools" data-pm="can-tools">
        {#each tools as [tool, has] (tool)}
          <span class="pp-tool" data-has={has ? 'true' : 'false'}>{#if has}{t(`pack.machines.tool.${tool}`)}{:else}<s>{t(`pack.machines.tool.${tool}`)}</s>{/if}</span>
        {/each}
      </div>
      {#if can.installing}<p class="pp-hint" data-pm="installing">{t('roster.can.installing', { tool: can.installing })}</p>{/if}
    {/if}
    <h3 class="pp-k">{t('roster.can.labels.title')}</h3>
    <LabelEditor machine={c.id} labels={can?.labels ?? []} {api} onSaved={() => void packMachines.refresh(true)} />
    {#if pressure}<p class="pp-hint" data-pm="pressure">{pressureLine(pressure, t)}</p>{/if}
    {#if snap}
      <p class="pp-reserve" data-pm="can-rules">
        <Button size="sm" onclick={onWork} data-act="takes-work">{t('roster.can.takes_work', { state: onOff(snap.restrictions.may_host_agents) })}</Button>
        <Button size="sm" onclick={onWork} data-act="may-install">{t('roster.can.may_install', { state: onOff(snap.restrictions.may_install_tools) })}</Button>
      </p>
    {/if}
    {#if can}
      <p class="pp-reserve" data-pm="abilities-checked"><span data-pm="checked">{checked}</span>
        <Button size="sm" disabled={busy} onclick={() => void checkAgain()} data-act="check-again">{t('roster.can.check_again')}</Button></p>
    {/if}
    {#if error}<p class="pp-warn" role="alert" data-pm="abilities-error">{error}</p>{/if}
  </section>
{/if}
