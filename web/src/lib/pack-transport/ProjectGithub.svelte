<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import Field from '../base/Field.svelte';
  import Select from '../base/Select.svelte';
  import State from '../base/State.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import InfoTip from '../info-tip/InfoTip.svelte';
  import type { PublishCard, TransportView } from './transport-api';

  interface Props {
    view: TransportView;
    card: PublishCard | null;
    busy: boolean;
    done: string | null;
    error: string | null;
    onAccount: (account: string | null) => void;
    onPublish: (answers: { owner?: string; account?: string }) => void;
  }
  const { view, card, busy, done, error, onAccount, onPublish }: Props = $props();

  let owner = $state('');
  let account = $state('');

  const accountLine = $derived(
    view.air_gap ? t('pack.transport.account.air_gap')
      : !view.account ? t('pack.transport.account.none')
        : t('pack.transport.account.in_force', { account: view.account, source: t(`pack.transport.source.${view.source}`) }),
  );
</script>

<div class="dk-pagebody" data-pt="github">
  <h4 class="oc-sub">{t('pack.transport.account')}</h4>
  <div class="dk-desc"><p>{t('pack.deck.gh_one')}</p></div>
  {#if error}<State kind="error" inline title={error} data-pt="error" />{/if}
  <p class="dk-pad dk-line dk-line--primary" data-pt="account-line">{accountLine}</p>
  {#if !view.air_gap}
    {#if view.logged_in.length === 0}
      <State kind="warn" inline title={t('pack.transport.accounts_none')} />
    {:else}
      <div class="dk-fieldrow">
        <span class="dk-k">{t('pack.transport.account_pick')}</span>
        <Select aria-label={t('pack.transport.account_pick')} size="sm" disabled={busy} data-pt="account-pick" value={view.source === 'project' ? view.account ?? '' : ''}
          onchange={(e) => { const v = (e.currentTarget as HTMLSelectElement).value; if (v) onAccount(v); }}>
          <option value="">{t('pack.transport.account_choose')}</option>
          {#each view.logged_in as login (login)}<option value={login}>{login}</option>{/each}
        </Select>
        {#if view.source === 'project'}
          <Button size="sm" disabled={busy} data-pt="account-clear" onclick={() => onAccount(null)}>{t('pack.transport.account_clear')}</Button>
        {/if}
      </div>
    {/if}
  {/if}
  <h4 class="oc-sub">{t('pack.transport.rung')}{#if view.rung_reason} <InfoTip text={view.rung_reason} label={t('pack.transport.info_label')} />{/if}</h4>
  <p class="dk-pad dk-line dk-line--primary" data-pt="rung-line" data-rung={view.rung}>{t(`pack.transport.rung.${view.rung}`)}</p>
  {#if done}<State kind="empty" inline title={done} data-pt="publish-done" />{/if}
  {#if card?.offered}
    <div class="dk-pub" data-pt="publish">
      <h4 class="oc-sub">{t('pack.transport.publish_title')} <InfoTip text={t('pack.transport.publish_help')} label={t('pack.transport.info_label')} /></h4>
      <div class="dk-fieldrow"><span class="dk-k">{t('pack.transport.publish_name')}</span><code class="pk-code" data-pt="publish-name">{card.name}</code></div>
      <div class="dk-fieldrow">
        <span class="dk-k">{t('pack.transport.publish_owner')}</span>
        {#if card.owner}<code class="pk-code" data-pt="publish-owner">{card.owner}</code>
        {:else}<Field aria-label={t('pack.transport.publish_owner_ask')} placeholder={t('pack.transport.publish_owner_ask')} bind:value={owner} maxlength={64} data-pt="publish-owner-input" />{/if}
      </div>
      <div class="dk-fieldrow">
        <span class="dk-k">{t('pack.transport.publish_account')}</span>
        {#if card.account}<code class="pk-code" data-pt="publish-account">{card.account}</code>
        {:else}
          <Select aria-label={t('pack.transport.publish_account')} size="sm" bind:value={account} data-pt="publish-account-pick">
            <option value="">{t('pack.transport.account_choose')}</option>
            {#each view.logged_in as login (login)}<option value={login}>{login}</option>{/each}
          </Select>
        {/if}
      </div>
      <div class="dk-fieldrow">
        <Button variant="confirm" disabled={busy || (card.asks.includes('owner') && !owner.trim()) || (card.asks.includes('account') && !account)} data-pt="publish-go"
          onclick={() => onPublish({ ...(owner.trim() ? { owner: owner.trim() } : {}), ...(account ? { account } : {}) })}><Icon name="github" size={12} />{t('pack.transport.publish_go')}</Button>
      </div>
    </div>
  {/if}
</div>
