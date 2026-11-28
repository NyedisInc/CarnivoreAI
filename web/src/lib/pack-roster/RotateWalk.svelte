
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { apiErrorMessageOr } from '../errors/failure-reason';
  import Button from '../base/Button.svelte';
  import { browserLedgerHost } from '../ledger/ledger-host';
  import { startLogin, type RowActionDeps } from '../ledger/row-actions';
  import { statusNow, statusWords, STATUS_LOOK } from './removed-logins';
  import { cancellable, cancelArgent, cancelWords, endsWords, GITHUB_APPS_URL, namesProvider, readRotate, SEEN_LOOK, seenWords, startRotate, type ArgentState, type RotateCopy, type RotateState } from './rotate';

  const { nowMs }: { nowMs: number } = $props();
  let open = $state(false);
  let data = $state<RotateState | null>(null);
  let problem = $state<string | null>(null);
  let working = $state<string | null>(null);
  let notices = $state<Record<string, string>>({});
  let cancelled = $state<ArgentState[]>([]);
  const argentLive = $derived((data?.argent.copies ?? []).some((c) => cancellable(statusNow(c, nowMs))));

  async function load(): Promise<void> {
    try { data = await readRotate(); problem = null; } catch (e) { problem = apiErrorMessageOr(e, t('api.error.rotate_unavailable')); }
  }
  function toggle(): void { open = !open; if (open) void load(); }

  const deps: RowActionDeps = {
    host: browserLedgerHost(), t, stored: () => null,
    busy: (_kind, id) => { working = id; },
    isBusy: () => working !== null,
    notice: (id, message) => { const next = { ...notices }; if (message === null) delete next[id]; else next[id] = message; notices = next; },
    reread: load, close: () => {},
  };

  async function signIn(account: string): Promise<void> {
    if (working !== null) return;
    working = account;
    deps.notice(account, null);
    try { await startRotate(account); } catch (e) { deps.notice(account, apiErrorMessageOr(e, t('api.error.rotate_unavailable'))); working = null; return; }
    working = null;
    await startLogin(account, deps);
    void load();
  }

  async function cancelAtArgent(): Promise<void> {
    if (working !== null) return;
    working = 'argent';
    problem = null;
    try { cancelled = (await cancelArgent()).computers.map((c) => c.state); } catch (e) { problem = apiErrorMessageOr(e, t('api.error.rotate_unavailable')); }
    working = null;
    void load();
  }
</script>

{#snippet copyRows(copies: RotateCopy[])}
  {#each copies as copy, i (i)}
    {@const look = STATUS_LOOK[statusNow(copy, nowMs)]}
    <li class="pp-swrow" data-copy><span class="pp-dim">{copy.label ? t('pack.removed_logins.computer_named', { name: copy.label }) : t('pack.removed_logins.computer', { id: copy.install_id.slice(0, 8) })}</span>
      <span class="pp-st" data-shape={look.shape} data-tone={look.tone}><i class="pp-st__mark" aria-hidden="true"></i><span class="pp-st__word">{statusWords(copy, nowMs)}</span></span></li>
  {/each}
{/snippet}

<div data-rotate>
  <div class="pp-swrow">{#if open}<h4 class="pp-k">{t('pack.rotate.title')}</h4>{/if}
    <Button size="sm" data-act="rotate-open" aria-expanded={open} onclick={toggle}>{open ? t('pack.rotate.close') : t('pack.rotate.open')}</Button></div>
  {#if open}
    <p class="pp-hint">{t('pack.rotate.help')}</p>
    {#if problem}<p class="pp-err" role="alert">{problem}</p>{/if}
    {#if data}
      {#if data.accounts.length === 0 && data.unlisted.length === 0}<p class="pp-hint">{t('pack.rotate.empty')}</p>{/if}
      {#each data.accounts as acct (acct.account)}
        {@const look = SEEN_LOOK[acct.sign_in_seen]}
        <ul class="pp-grants" data-rotate-account={acct.account}>
          <li class="pp-swrow"><span>{acct.name}{#if !namesProvider(acct.name, acct.provider)}{' '}<span class="pp-dim">{t(`pack.removed_logins.kind.${acct.provider}`)}</span>{/if}</span>
            {#if acct.sign_in === 'app'}<Button size="sm" data-act="rotate-sign-in" disabled={working !== null} onclick={() => void signIn(acct.account)}>{t('pack.rotate.sign_in')}</Button>{/if}</li>
          {#if acct.sign_in === 'terminal'}<li class="pp-hint">{t('pack.rotate.terminal')}</li>
          {:else}
            <li class="pp-swrow" data-seen={acct.sign_in_seen}><span class="pp-st" data-shape={look.shape} data-tone={look.tone}><i class="pp-st__mark" aria-hidden="true"></i><span class="pp-st__word">{acct.sign_in_seen === 'other_account' ? t('pack.rotate.seen.other_account_short') : seenWords(acct.sign_in_seen)}</span></span></li>
            {#if acct.sign_in_seen === 'other_account'}<li class="pp-hint">{seenWords(acct.sign_in_seen)}</li>{/if}
          {/if}
          {#if notices[acct.account]}<li class="pp-err" role="alert" data-notice>{notices[acct.account]}</li>{/if}
          {@render copyRows(acct.copies)}
          {#if acct.copies.length > 0}<li class="pp-hint" data-ends={acct.sign_in_ends}>{endsWords(acct.sign_in_ends)}</li>{/if}
        </ul>
      {/each}
      {#each data.unlisted as other (other.account + other.provider)}
        <ul class="pp-grants" data-rotate-unlisted={other.account}>
          <li class="pp-swrow"><span>{other.account}{#if !namesProvider(other.account, other.provider)}{' '}<span class="pp-dim">{t(`pack.removed_logins.kind.${other.provider}`)}</span>{/if}</span></li>
          {@render copyRows(other.copies)}
          <li class="pp-hint">{t('pack.rotate.unlisted.help')}</li>
        </ul>
      {/each}
      {#if data.argent.copies.length > 0 || !data.argent.known}
        <ul class="pp-grants" data-rotate-argent>
          <li class="pp-swrow"><span>{t('pack.rotate.argent.title')}</span>
            {#if argentLive}<Button variant="danger" size="sm" data-act="rotate-argent" disabled={working !== null} onclick={() => void cancelAtArgent()}>{t('pack.rotate.argent.cancel')}</Button>{/if}</li>
          {#if data.argent.known}{#if argentLive}<li class="pp-hint">{t('pack.rotate.argent.help')}</li>{/if}{:else}<li class="pp-hint">{t('pack.removed_logins.argent_unknown')}</li>{/if}
          {@render copyRows(data.argent.copies)}
          {#each cancelWords(cancelled) as line (line)}<li class="pp-hint" data-cancelled>{line}</li>{/each}
        </ul>
      {/if}
      {#if data.not_tracked.includes('github')}
        <ul class="pp-grants" data-rotate-github>
          <li class="pp-swrow"><span>github</span></li>
          <li class="pp-hint">{t('pack.rotate.github.help')}</li>
          <li class="pp-swrow"><a href={GITHUB_APPS_URL} target="_blank" rel="noopener noreferrer">{t('pack.rotate.github.link')}</a></li>
        </ul>
      {/if}
    {/if}
  {/if}
</div>
