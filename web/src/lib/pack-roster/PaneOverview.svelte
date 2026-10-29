
<script lang="ts">
  import Button from '../base/Button.svelte';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import Meters from './Meters.svelte';
  import ComputerUpdate from '../computers/ComputerUpdate.svelte';
  import { ageWords, dialWords } from '../computers/computers-format';
  import { setDirection, activity } from '../computers/computers-store.svelte';
  import { rosterActivity } from './roster-store.svelte';
  import { dialKey } from './Status.svelte';
  import type { RosterComputer } from './roster-model';

  const TOOLS = ['python3.12', 'python3', 'node', 'npm', 'git', 'gh', 'docker', 'tmux', 'claude', 'playwright', 'playwright_browsers'] as const;

  const { c, onWork, nowMs }: { c: RosterComputer; onWork: () => void; nowMs: number } = $props();
  const chain = $derived(c.machine?.snapshot?.toolchain ?? null);
  const specs = $derived(c.machine?.specs ?? null);
  const dialWord = $derived(t(`roster.dial.${dialKey(c)}`));
  const dialLine = $derived(
    c.since ? t('roster.ov.since', { word: dialWord, time: c.since })
      : c.entry?.firewall_on && c.entry.dial?.state === 'unreachable' ? t('roster.ov.firewall', { word: dialWord }) : dialWord,
  );
  const help = $derived(c.entry ? dialWords({ label: c.name, dial: c.entry.dial, firewall_on: c.entry.firewall_on }) : null);
  const dupName = $derived(c.entry?.possible_duplicate_of ?? null);
  const joined = $derived(c.entry?.joined_at ? ageWords(c.entry.joined_at, nowMs) : c.isSelf ? t('roster.card.this') : null);
</script>

<section class="m1-sec"><h3 class="pp-k">{t('roster.ov.load')}</h3><Meters {c} /></section>
{#if c.kind !== 'ssh-only'}
  <p class="m1-setwork"><span class="pp-hint">{t('roster.ov.reserve_hint')}</span>
    <Button variant="quiet" size="sm" onclick={onWork}>{t('roster.ov.set_in_work')}</Button></p>
{/if}
<section class="m1-sec"><h3 class="pp-k">{t('roster.ov.tools')}</h3>
  <div class="pp-tools" data-pm="toolchain">
    {#if chain}
      {#each TOOLS.filter((x) => x in chain) as tool (tool)}
        <span class="pp-tool" data-has={chain[tool] === true ? 'true' : 'false'}>{#if chain[tool] === true}{t(`pack.machines.tool.${tool}`)}{:else}<s>{t(`pack.machines.tool.${tool}`)}</s>{/if}</span>
      {/each}
    {:else}<span class="pp-dim">-</span>{/if}
  </div>
</section>
<section class="m1-sec"><h3 class="pp-k">{t('roster.ov.details')}</h3>
  <dl class="pp-facts">
    <dt>{t('roster.ov.model')}</dt><dd>{specs?.model ?? '-'}</dd>
    <dt>{t('roster.ov.cores')}</dt><dd>{specs?.cores ?? '-'}</dd>
    <dt>{t('roster.ov.memory')}</dt><dd>{specs?.mem_total_gb != null ? t('roster.card.gb', { n: Math.round(specs.mem_total_gb) }) : '-'}</dd>
    <dt>{t('roster.ov.app_version')}</dt><dd>{c.machine?.snapshot?.app_version ?? '-'}</dd>
    <dt>{t('roster.ov.in_pack')}</dt><dd>{t(`roster.kind.${c.kind}`)}</dd>
    <dt>{t('roster.ov.joined')}</dt><dd>{joined ?? '-'}</dd>
    <dt>{t('roster.ov.last_seen')}</dt><dd>{c.isSelf ? t('roster.card.this') : c.lastSeen ? ageWords(c.lastSeen, nowMs) : t('roster.card.never_seen')}</dd>
    <dt>{t('roster.ov.dial')}</dt><dd>{dialLine}</dd>
  </dl>
</section>
{#if help}<p class="pp-hint">{help}</p>{/if}
{#if dupName}<p class="pp-warn" role="status">{t('roster.ov.duplicate', { name: dupName })}</p>{/if}
{#if c.isSelf || c.entry?.host_key}
  <section class="m1-sec" data-pm="app-update"><h3 class="pp-k">{t('roster.ov.app_update')}</h3>
    <ComputerUpdate hostKey={c.isSelf ? '' : (c.entry?.host_key ?? '')} /></section>
{/if}
{#if c.entry && !c.isSelf}
  <section class="m1-sec"><h3 class="pp-k">{t('roster.ov.control')}</h3>
    <Check label={t('computers.row.control', { label: c.entry.label })} checked={c.entry.direction !== 'one_way'} role="switch" disabled={activity.busy !== null || rosterActivity.busy !== null}
      data-cmp="direction" onToggle={(next) => void setDirection(c.entry!.install_id, next)} />
    {#if c.entry.direction === 'one_way'}<p class="pp-hint">{t('computers.row.one_way_note', { label: c.entry.label })}</p>{/if}
  </section>
{/if}
<p class="pp-hint">{t('computers.footer.awake')}</p>
