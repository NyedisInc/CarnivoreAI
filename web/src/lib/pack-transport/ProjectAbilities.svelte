<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import { ageWords } from '../computers/computers-format';
  import Button from '../base/Button.svelte';
  import State from '../base/State.svelte';
  import Tag from '../base/Tag.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import InfoTip from '../info-tip/InfoTip.svelte';
  import { packMachines } from '../pack-machines/pack-machines-store.svelte';
  import { abilitiesApi, type AbilitiesApi } from '../pack-roster/abilities-api';
  import LabelEditor from '../pack-roster/LabelEditor.svelte';
  import { sshTargetsApi, type SshTargetsApi } from '../pack-ssh-targets/ssh-targets-api';
  import { loadSshTargets, sshTargets } from '../pack-ssh-targets/ssh-targets-store.svelte';
  import ComputerGlyph from './ComputerGlyph.svelte';
  import { chipRows, type Facts } from './abilities-words';

  let { api = abilitiesApi, sshApi = sshTargetsApi }: { api?: AbilitiesApi; sshApi?: SshTargetsApi } = $props();

  interface Entry {
    key: string;
    name: string;
    glyph: 'self' | 'linked' | 'down';
    ssh: boolean;
    old: boolean;
    away: boolean;
    facts: Facts | null;
    labels: string[];
    probedAt: number | null;
    machine: string;
    takesWork: boolean;
  }

  let busy = $state<string | null>(null);
  let errors = $state<Record<string, string>>({});
  const now = $derived(Date.now());

  const entries = $derived.by((): Entry[] => {
    const own: Entry[] = [];
    for (const m of packMachines.data?.machines ?? []) {
      if (!m.is_self && !m.paired) continue;
      const can = m.snapshot?.can ?? null;
      const connected = m.is_self || m.state === 'connected';
      own.push({
        key: m.install_id, name: m.label || m.install_id.slice(0, 8), glyph: m.is_self ? 'self' : connected ? 'linked' : 'down', ssh: false,
        old: connected && !can, away: !connected,
        facts: can ?? (connected && m.snapshot?.toolchain ? { tools: m.snapshot.toolchain } : null), labels: can?.labels ?? [], probedAt: can?.probed_at ?? null,
        machine: m.install_id, takesWork: true,
      });
    }
    own.sort((a, b) => Number(b.glyph === 'self') - Number(a.glyph === 'self'));
    const far = sshTargets.list.map((s): Entry => ({
      key: s.host_key, name: s.label, glyph: 'linked', ssh: true, old: false, away: false, facts: s.can ?? null, labels: s.can?.labels ?? [],
      probedAt: s.age_s != null ? Date.now() / 1000 - s.age_s : null, machine: s.host_key, takesWork: s.takes_work,
    }));
    return [...own, ...far];
  });

  async function check(e: Entry): Promise<void> {
    if (busy) return;
    busy = e.key;
    delete errors[e.key];
    try {
      if (e.ssh) { await sshApi.check(e.machine); await loadSshTargets(sshApi); } else { await api.rescan(e.machine); await packMachines.refresh(true); }
    } catch (failure) {
      errors[e.key] = nonEmptyErrorMessageOr(failure, t('roster.can.failed'));
    } finally {
      busy = null;
    }
  }

  function labelApi(e: Entry): AbilitiesApi {
    if (!e.ssh) return api;
    return { ...api, putLabels: async (hostKey, labels) => (await sshApi.set(hostKey, { takes_work: e.takesWork, labels })).can?.labels ?? labels };
  }

  const checked = (e: Entry): string => (e.probedAt && now / 1000 - e.probedAt > 60 ? t('roster.can.checked', { age: ageWords(new Date(e.probedAt * 1000).toISOString(), now) }) : t('roster.can.checked_recent'));

  onMount(() => { void loadSshTargets(sshApi); });
</script>

<div class="dk-pagebody" data-pt="abilities">
  <h4 class="oc-sub">{t('pack.deck.caps_title')} <InfoTip text={t('pack.deck.caps_help')} label={t('pack.transport.info_label')} /></h4>
  <div class="dk-desc">
    <p>{t('pack.deck.cap_what')}</p>
    <p><b>{t('pack.deck.found_title')}</b> {t('pack.deck.cap_found')}</p>
    <p><b>{t('pack.deck.labels_title')}</b> {t('pack.deck.cap_labels')}</p>
  </div>
  {#each entries as e (e.key)}
    {@const rows = e.facts ? chipRows(e.facts, t) : { main: [], basic: [] }}
    <section class="dk-cap" data-cap={e.key} data-stale={e.away ? '' : undefined}>
      <div class="dk-cap__head">
        <ComputerGlyph kind={e.glyph} />
        <span class="dk-cap__name">{e.name}</span>
        {#if e.ssh}<Tag>{t('pack.deck.ssh_tag')}</Tag>{/if}
        {#if e.old}<Tag tone="warn">{t('pack.deck.old_tag')}</Tag>{/if}
        {#if !e.old && !e.away && e.probedAt}
          <span class="dk-end">
            <span class="dk-line" data-checked>{checked(e)}</span>
            <Button variant="secondary" size="sm" disabled={busy !== null} data-act="check-again" onclick={() => void check(e)}><Icon name="refresh" size={12} />{t('roster.can.check_again')}</Button>
          </span>
        {/if}
      </div>
      {#if e.old}<State kind="warn" inline title={t('pack.deck.old_caps')} />
      {:else if e.away}<State kind="warn" inline title={t('pack.deck.away_caps')} />{/if}
      {#if !e.away}
        <div class="dk-set" data-set="found">
          <div class="dk-set__h"><span class="dk-set__t">{t('pack.deck.found_title')}</span></div>
          {#if rows.main.length === 0 && rows.basic.length === 0}<span class="dk-line">{t('pack.deck.no_report')}</span>{/if}
          {#if rows.main.length}<div class="dk-cap__chips" data-has>{#each rows.main as w (w)}<Tag>{w}</Tag>{/each}</div>{/if}
          {#if rows.basic.length}<div class="dk-cap__chips dk-cap__chips--basic" data-basics>{#each rows.basic as w (w)}<Tag>{w}</Tag>{/each}</div>{/if}
        </div>
        {#if !e.old}
          <div class="dk-set" data-set="labels" data-labels={e.key}>
            <div class="dk-set__h"><span class="dk-set__t">{t('pack.deck.labels_title')}</span></div>
            <LabelEditor machine={e.machine} labels={e.labels} api={labelApi(e)} onSaved={() => void (e.ssh ? loadSshTargets(sshApi) : packMachines.refresh(true))} />
          </div>
        {/if}
      {:else}
        <State kind="warn" inline title={t('pack.deck.labels_away')} />
      {/if}
      {#if errors[e.key]}<State kind="error" inline title={errors[e.key]} />{/if}
    </section>
  {/each}
  {#if entries.length < 2}<State kind="empty" inline title={t('pack.autodelegate.no_computers')} />{/if}
</div>
