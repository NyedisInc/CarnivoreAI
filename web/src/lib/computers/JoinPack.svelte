<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { tick } from 'svelte';
  import { activity, join, look } from './computers-store.svelte';
  import PackOffers from '../pack-offers/PackOffers.svelte';
  import { codeCopy } from './computers-format';
  import CopyField from '../settings-page/CopyField.svelte';
  import { HELPER_LINE } from '../first-run/join-api';

  let value = $state('');
  let field = $state<HTMLInputElement | null>(null);
  let picked = $state<string | null>(null);
  let declined = $state<string[]>([]);
  const status = $derived(activity.join);
  const running = $derived(status !== null && ['waiting_relay', 'finding', 'connecting', 'checking', 'linking'].includes(status.state)
    && !(activity.looking && status.state === 'finding' && status.candidates.length > 0));
  const found = $derived(status !== null && status.state === 'finding' && status.error === null ? status.candidates : []);
  const candidates = $derived(activity.looking ? [] : found);
  const offers = $derived(!activity.looking ? [] : found.filter((c) => !declined.includes(c.fid)).map((c) => ({ fid: c.fid, label: c.label ?? `${c.name} ${c.fid_short}` })));

  function startLook(): void {
    picked = null;
    declined = [];
    void look();
  }

  function accept(offer: { fid: string }): void {
    picked = offer.fid;
    void tick().then(() => field?.focus());
  }

  function bodyOf(candidate?: string): { code?: string; link?: string; candidate_fid?: string } {
    const text = value.trim();
    const base = text.startsWith('carnivore://') ? { link: text } : { code: text.replace(/\s+/g, '') };
    return candidate ? { ...base, candidate_fid: candidate } : base;
  }
</script>

<div class="cmp-region" data-cmp="join">
  <h3 class="pl-label">{t('computers.join.title')}</h3>
  <p class="cmp-note" data-cmp="join-warning">{t('computers.join.warning', { main: t('computers.join.main_fallback') })}</p>
  <form class="cmp-form" onsubmit={(e) => { e.preventDefault(); void join(bodyOf(picked ?? undefined)); }}>
    <label class="cmp-field"><span class="pl-label">{t('computers.join.code_label')}</span>
      <input class="oc-field" type="text" autocomplete="off" autocapitalize="off" spellcheck="false" bind:value bind:this={field}
        placeholder={t('computers.join.placeholder')} data-cmp="join-input" /></label>
    <button type="submit" class="modal-btn modal-btn-confirm" data-cmp="join-go" disabled={value.trim() === '' || running || activity.busy !== null}>
      {t('computers.join.go')}</button>
  </form>
  <div class="cmp-offers">
    <PackOffers {offers} {picked} busy={activity.busy !== null || (running && offers.length === 0)} attr="data-cmp" btn="modal-btn modal-btn-secondary"
      btnConfirm="modal-btn modal-btn-confirm" onLook={startLook} onYes={accept} onNo={(offer) => (declined = [...declined, offer.fid])} />
  </div>
  {#if candidates.length > 0}
    <div data-cmp="join-pick">
      <p class="cmp-note">{t('computers.join.pick')}</p>
      {#each candidates as pack (pack.fid)}
        <button type="button" class="modal-btn modal-btn-secondary" data-fid={pack.fid} onclick={() => void join(bodyOf(pack.fid))}>
          {pack.name} <span class="cmp-fp">{pack.fid_short}</span></button>
      {/each}
    </div>
  {/if}
  {#if status !== null && running}
    <p class="cmp-note" data-cmp="join-step">{activity.looking ? t('first_run.join.step.looking') : t(`computers.join.step.${status.state}`)}</p>
  {:else if status !== null && status.state === 'joined'}
    <p class="cmp-note" data-cmp="join-done">{t('computers.join.done', { name: status.main_label ?? t('computers.join.main_fallback') })}</p>
  {:else if status !== null && status.error !== null}
    <p class="cmp-blocker" data-cmp="join-error">{codeCopy('first_run.join.error', status.error, 'computers.join.error.generic')}</p>
    {#if status.error === 'helper_not_started' || status.error === 'no_relay'}
      <CopyField value={HELPER_LINE} {t} label={t('first_run.join.helper_line_label')} valueAttrs={{ 'data-cmp': 'helper-line' }} />
    {/if}
  {/if}
</div>
