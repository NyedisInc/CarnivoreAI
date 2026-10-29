
<script lang="ts">
  import { tick } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { activity, join, look } from '../computers/computers-store.svelte';
  import PackOffers from '../pack-offers/PackOffers.svelte';
  import { codeCopy } from '../computers/computers-format';
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

  function startLook(): void { picked = null; declined = []; void look(); }
  function accept(offer: { fid: string }): void { picked = offer.fid; void tick().then(() => field?.focus()); }
  function bodyOf(candidate?: string): { code?: string; link?: string; candidate_fid?: string } {
    const text = value.trim();
    const base = text.startsWith('carnivore://') ? { link: text } : { code: text.replace(/\s+/g, '') };
    return candidate ? { ...base, candidate_fid: candidate } : base;
  }
</script>

<section class="m1-sec" data-sec="join" data-cmp="join"><h3 class="pp-k">{t('roster.sets.join')}</h3>
  <form class="pp-form" onsubmit={(e) => { e.preventDefault(); void join(bodyOf(picked ?? undefined)); }}>
    <p class="pp-hint" data-cmp="join-warning">{t('roster.sets.join_hint')}</p>
    <div class="pp-fieldrow"><label class="pp-k" for="rs-join-code">{t('roster.sets.code_label')}</label>
      <input id="rs-join-code" class="oc-field pp-input" type="text" autocomplete="off" autocapitalize="off" spellcheck="false" bind:value bind:this={field}
        placeholder={t('computers.join.placeholder')} data-cmp="join-input" /></div>
    <div class="pp-acts"><button type="submit" class="oc-btn oc-btn--confirm" data-cmp="join-go" disabled={value.trim() === '' || running || activity.busy !== null}>{t('computers.join.go')}</button></div>
  </form>
  {#if candidates.length > 0}
    <div class="pp-form" data-cmp="join-pick">
      <p class="pp-hint">{t('computers.join.pick')}</p>
      <div class="pp-acts">{#each candidates as pack (pack.fid)}
        <button type="button" class="oc-btn" data-fid={pack.fid} onclick={() => void join(bodyOf(pack.fid))}>{pack.name} {pack.fid_short}</button>
      {/each}</div>
    </div>
  {/if}
  {#if status !== null && running}
    <p class="pp-hint" data-cmp="join-step">{activity.looking ? t('first_run.join.step.looking') : t(`computers.join.step.${status.state}`)}</p>
  {:else if status !== null && status.state === 'joined'}
    <p class="pp-hint" data-cmp="join-done">{t('computers.join.done', { name: status.main_label ?? t('computers.join.main_fallback') })}</p>
  {:else if status !== null && status.error !== null}
    <p class="pp-err" data-cmp="join-error">{codeCopy('first_run.join.error', status.error, 'computers.join.error.generic')}</p>
    {#if status.error === 'helper_not_started' || status.error === 'no_relay'}
      <CopyField value={HELPER_LINE} {t} label={t('first_run.join.helper_line_label')} valueAttrs={{ 'data-cmp': 'helper-line' }} />
    {/if}
  {/if}
</section>
<section class="m1-sec" data-sec="look"><h3 class="pp-k">{t('roster.sets.look')}</h3>
  <div class="pp-form"><p class="pp-hint">{t('roster.sets.look_hint')}</p>
    <div class="pp-acts">
      <PackOffers {offers} {picked} busy={activity.busy !== null || (running && offers.length === 0)} attr="data-cmp" btn="oc-btn" btnConfirm="oc-btn oc-btn--confirm"
        onLook={startLook} onYes={accept} onNo={(offer) => (declined = [...declined, offer.fid])} />
    </div></div>
</section>
