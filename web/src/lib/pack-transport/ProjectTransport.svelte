<script lang="ts">
  import './pack-transport.css';
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import Check from '../../opscenter/ui/Check.svelte';
  import Button from '../base/Button.svelte';
  import Field from '../base/Field.svelte';
  import Select from '../base/Select.svelte';
  import ProjectReplicas from './ProjectReplicas.svelte';
  import { transportApi, type PublishCard, type TransportApi, type TransportView } from './transport-api';

  let { name, api = transportApi, startOpen = false }: { name: string; api?: TransportApi; startOpen?: boolean } = $props();

  // svelte-ignore state_referenced_locally
  let open = $state(startOpen);
  let view = $state<TransportView | null>(null);
  let card = $state<PublishCard | null>(null);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let done = $state<string | null>(null);
  let owner = $state('');
  let account = $state('');

  async function load(): Promise<void> {
    try {
      view = await api.read(name);
      card = await api.card(name).catch(() => null);
      error = null;
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.transport.error.failed'));
    }
  }

  async function change(send: () => Promise<unknown>): Promise<void> {
    if (busy) return;
    busy = true;
    error = null;
    try {
      await send();
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.transport.error.failed'));
    } finally {
      busy = false;
      await load();
    }
  }

  function toggle(): void {
    open = !open;
    if (open && !view) void load();
  }

  async function publish(): Promise<void> {
    if (busy || !card) return;
    busy = true;
    error = null;
    done = null;
    try {
      const made = await api.publish(name, {
        ...(owner.trim() ? { owner: owner.trim() } : {}),
        ...(account ? { account } : {}),
      });
      done = t('pack.transport.publish_done', { url: made.url });
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.transport.error.failed'));
    } finally {
      busy = false;
      await load();
    }
  }

  $effect(() => {
    if (startOpen && !view) void load();
  });

  const accountLine = $derived.by(() => {
    if (!view) return '';
    if (view.air_gap) return t('pack.transport.account.air_gap');
    if (!view.account) return t('pack.transport.account.none');
    return t('pack.transport.account.in_force', { account: view.account, source: t(`pack.transport.source.${view.source}`) });
  });
</script>

<div class="pt" data-pt="root">
  {#if !startOpen}
    <Button variant="quiet" size="sm" aria-expanded={open} style="--_btn-ink: var(--oc-text-dim)" data-pt="toggle" onclick={toggle}>
      {open ? t('pack.transport.close') : t('pack.transport.open')}</Button>
  {/if}
  {#if open}
    <div class="pt-body" data-pt="body">
      <h3 class="oc-label">{t('pack.transport.title')}</h3>
      {#if error}<p class="pt-error" role="alert" data-pt="error">{error}</p>{/if}
      {#if !view}
        {#if !error}<p class="pt-note">{t('pack.transport.loading')}</p>{/if}
      {:else}
        <Check label={t('pack.transport.air_gap')} hint={t('pack.transport.air_gap_help')} checked={view.air_gap} role="switch"
          disabled={busy} data-pt="air-gap" onToggle={(next) => void change(() => api.setAirGap(name, next))} />
        <div class="pt-row" data-pt="account">
          <span class="oc-sub">{t('pack.transport.account')}</span>
          <span class="pt-line" data-pt="account-line">{accountLine}</span>
          {#if !view.air_gap}
            {#if view.logged_in.length === 0}
              <span class="pt-note">{t('pack.transport.accounts_none')}</span>
            {:else}
              <Select label={t('pack.transport.account_pick')} disabled={busy} data-pt="account-pick" value={view.source === 'project' ? view.account ?? '' : ''}
                onchange={(e) => { const v = (e.currentTarget as HTMLSelectElement).value; if (v) void change(() => api.setAccount(name, v)); }}>
                <option value="">{t('pack.transport.account_choose')}</option>
                {#each view.logged_in as login (login)}<option value={login}>{login}</option>{/each}
              </Select>
            {/if}
            {#if view.source === 'project'}
              <Button variant="quiet" size="sm" disabled={busy} data-pt="account-clear"
                onclick={() => void change(() => api.setAccount(name, null))}>{t('pack.transport.account_clear')}</Button>
            {/if}
          {/if}
        </div>
        <div class="pt-row" data-pt="rung">
          <span class="oc-sub">{t('pack.transport.rung')}</span>
          <span class="pt-line" data-pt="rung-line" data-rung={view.rung}>{t(`pack.transport.rung.${view.rung}`)}</span>
          <span class="pt-note">{view.rung_reason}</span>
        </div>
        <ProjectReplicas {name} />
        {#if card?.offered}
          <div class="pt-publish" data-pt="publish">
            <h4 class="oc-label">{t('pack.transport.publish_title')}</h4>
            <p class="pt-note">{t('pack.transport.publish_help')}</p>
            <p class="pt-line" data-pt="publish-name">{t('pack.transport.publish_name')}: {card.name}</p>
            {#if card.owner}
              <p class="pt-line" data-pt="publish-owner">{t('pack.transport.publish_owner')}: {card.owner}</p>
            {:else}
              <Field label={t('pack.transport.publish_owner_ask')} bind:value={owner} maxlength={64} data-pt="publish-owner-input" />
            {/if}
            {#if card.account}
              <p class="pt-line" data-pt="publish-account">{t('pack.transport.publish_account')}: {card.account}</p>
            {:else}
              <Select label={t('pack.transport.publish_account')} bind:value={account} data-pt="publish-account-pick">
                <option value="">{t('pack.transport.account_choose')}</option>
                {#each view.logged_in as login (login)}<option value={login}>{login}</option>{/each}
              </Select>
            {/if}
            <div class="pt-actions">
              <Button variant="confirm" disabled={busy || (card.asks.includes('owner') && !owner.trim()) || (card.asks.includes('account') && !account)}
                data-pt="publish-go" onclick={() => void publish()}>{t('pack.transport.publish_go')}</Button>
            </div>
          </div>
        {/if}
        {#if done}<p class="pt-done" role="status" data-pt="publish-done">{done}</p>{/if}
      {/if}
    </div>
  {/if}
</div>
