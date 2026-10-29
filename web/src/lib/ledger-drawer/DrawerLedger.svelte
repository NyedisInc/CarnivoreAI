<script lang="ts">
  import { untrack } from 'svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import IconButton from '../base/IconButton.svelte';
  import { ledger, primarySessionId, type AccountUsage, type LedgerSnapshot, type Resource } from '../../opscenter/api';
  import { PRIMARY_BIND_EVENT } from '../../opscenter/engine/primary-bind';
  import { releaseSessionUsage, sessionUsage } from '../../opscenter/api/session-usage.svelte';
  import { sortAccounts } from '../../opscenter/cells/ledger/meta';
  import { sessions } from '../../opscenter/api/sessions.svelte';
  import { groupSessionsByAccount, type ProviderSession } from '../ledger/ledger-sessions';
  import { credentialLabel, credentialTone, formatAge } from '../ledger/ledger-model';
  import { providerMark } from '../sessions/agent-marks';
  import { t } from '../i18n/index.svelte';
  import { windowLabels } from '../../../../client/js/labels/usage-panel.js';
  import { LEDGER_HASH, ledgerAccountHash, openLedgerScreen } from '../ledger/screen-host';
  import { longWindow, recommend, shortWindow } from './recommend';
  import { FOLDS, nextFold, readFold, writeFold, type LedgerFold } from './ledger-fold';
  import LedgerGlanceView from './LedgerGlanceView.svelte';
  import AutoSwitchIcon from '../account-switch/AutoSwitchIcon.svelte';
  import SwitchAccountButton from '../account-switch/SwitchAccountButton.svelte';
  import { accountSwitch } from '../account-switch/switch-store.svelte';
  import Tag from '../base/Tag.svelte';
  import type { TagTone } from '../base/classes';
  import LimitGauge from '../../opscenter/ui/LimitGauge.svelte';
  import type { WidgetHandle } from '../../opscenter/widgets/shell/define-widget.svelte';

  const TAG_TONE: Readonly<Record<string, TagTone>> = { warn: 'warn', high: 'danger', unknown: 'neutral' };

  interface Bar {
    key: string;
    label: string;
    segments: number;
    filled: number;
    scale: number | null;
    paceElapsedPct: number | null;
    paceState: 'on' | 'ahead' | 'over' | null;
    percentText: string;
    meterText: string;
    resetText: string;
  }

  let {
    source = ledger,
    activeAccount = undefined,
    startOpen = undefined,
    embedded = false,
    sessionRows = undefined,
    widget = undefined,
  }: {
    source?: Resource<LedgerSnapshot>;
    activeAccount?: string | null;
    startOpen?: boolean;
    embedded?: boolean;
    sessionRows?: readonly ProviderSession[];
    widget?: WidgetHandle;
  } = $props();

  const readStoredFold = (): LedgerFold => (widget ? (widget.state.fold as LedgerFold) : readFold());
  const keepFold = (next: LedgerFold): void => {
    if (widget) widget.state.fold = next;
    else writeFold(next);
  };

  let fold = $state<LedgerFold>(
    untrack(() => (startOpen !== undefined ? (startOpen ? 'expanded' : 'compact') : readStoredFold())),
  );
  let now = $state(Date.now());

  $effect(() => {
    const timer = setInterval(() => {
      now = Date.now();
      if (startOpen === undefined) fold = readStoredFold();
    }, 5000);
    return () => clearInterval(timer);
  });

  const snapshot = $derived(source.data);
  const accounts = $derived(snapshot ? sortAccounts(snapshot.accounts, accountSwitch.data) : []);

  const openCounts = $derived(
    groupSessionsByAccount(
      sessionRows ?? (source === ledger ? (sessions.data ?? []) : []),
      accounts.map((a) => a.id),
    ).byAccount,
  );
  const picked = $derived(new Set(recommend(accounts, now).map((a) => a.pick?.account.id).filter(Boolean)));
  const staleRead = $derived(snapshot !== null && source.status !== 'ok');

  const noAccountsConfigured = $derived(snapshot !== null && snapshot.accounts.length === 0);

  let primaryId = $state(primarySessionId());

  $effect(() => {
    primaryId = primarySessionId();
    const onBind = (event: Event): void => {
      const id = (event as CustomEvent<{ sessionId?: string }>).detail?.sessionId;
      if (id) primaryId = id;
    };
    globalThis.addEventListener(PRIMARY_BIND_EVENT, onBind);
    return () => globalThis.removeEventListener(PRIMARY_BIND_EVENT, onBind);
  });

  let usage = $state<ReturnType<typeof sessionUsage> | null>(null);

  $effect(() => {
    const id = primaryId;
    if (!id) {
      usage = null;
      return;
    }
    usage = sessionUsage(id);
    return () => releaseSessionUsage(id);
  });

  const activeAccountId = $derived(
    activeAccount !== undefined ? activeAccount : usage?.data?.account?.id ?? null,
  );

  const notice = $derived.by((): string => {
    if (snapshot) return snapshot.accounts.length ? '' : t('opscenter.ledger.no_accounts');
    if (source.status === 'loading') return t('opscenter.ledger.loading');
    if (source.status === 'signed-out') return t('opscenter.ledger.signed_out');
    if (source.status === 'unavailable') return t('opscenter.ledger.unavailable');
    return t('opscenter.ledger.error', { reason: source.error ?? t('opscenter.value.read_failed') });
  });

  const updated = $derived(
    source.fetchedAt === null
      ? ''
      : t('ledger.drawer.updated', { age: formatAge(new Date(source.fetchedAt).toISOString(), now, t) }),
  );

  const loopStopped = $derived(
    snapshot && !snapshot.loop.alive
      ? t('ledger.loop.stopped', { age: formatAge(snapshot.loop.last_pass_at, now, t) })
      : '',
  );

  function providerName(provider: string): string {
    return provider === 'claude' || provider === 'codex' ? t(`ledger.editor.provider_${provider}`) : provider;
  }

  function nameOf(account: AccountUsage): string {
    return account.short_name || account.name;
  }

  function bars(account: AccountUsage): Bar[] {
    return windowLabels(account, t, now) as Bar[];
  }

  function compactBars(account: AccountUsage): Bar[] {
    return account.credential_state === 'ok' ? shortLongBars(account) : [];
  }

  function shortLongBars(account: AccountUsage): Bar[] {
    const all = bars(account);
    return [shortWindow(account), longWindow(account)]
      .map((w) => (w ? all.find((b) => b.key === `window:${w.kind}`) : undefined))
      .filter((b): b is Bar => b !== undefined);
  }

  const totalBars = $derived(snapshot ? shortLongBars({ windows: snapshot.total?.windows ?? [] } as unknown as AccountUsage) : []);

  function isStale(account: AccountUsage): boolean {
    return staleRead || (account.credential_state !== 'ok' && account.windows.length > 0);
  }

  function needsReadd(account: AccountUsage): boolean {
    if (account.credential_state === 'missing' || account.credential_state === 'expired') return true;
    const poke = account.poke?.state;
    return poke === 'failed' || poke === 'unknown';
  }

  function readd(event: MouseEvent, id: string): void {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const pin = (globalThis as { SessionSidebarPin?: { closeAfterSwitch?: () => void } }).SessionSidebarPin;
    pin?.closeAfterSwitch?.();
    openLedgerScreen(id);
  }

  function openProviders(event: MouseEvent): void {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const pin = (globalThis as { SessionSidebarPin?: { closeAfterSwitch?: () => void } }).SessionSidebarPin;
    pin?.closeAfterSwitch?.();
    openLedgerScreen();
  }

  function onTitleClick(event: MouseEvent): void {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    toggle();
  }

  function onTitleKeydown(event: KeyboardEvent): void {
    if (event.key !== ' ' && event.key !== 'Spacebar') return;
    event.preventDefault();
    toggle();
  }

  function foldLabel(current: LedgerFold): string {
    return `${t(`ledger.drawer.fold_${current}`)}, ${t('ledger.drawer.fold_position', { n: String(FOLDS.indexOf(current) + 1), total: String(FOLDS.length) })}`;
  }

  function toggle(): void {
    keepFold(nextFold(fold));
    fold = readStoredFold();
  }

  function onHeadClick(event: MouseEvent): void {
    if ((event.target as Element).closest('a, button, [role="button"]')) return;
    toggle();
  }
</script>

{#snippet bar(b: Bar, height: number, dim: boolean)}
  <LimitGauge segments={b.segments} filled={b.filled} scale={b.scale} paceElapsedPct={b.paceElapsedPct} paceState={b.paceState} meterText={b.meterText} {height} {dim} />
{/snippet}

{#if noAccountsConfigured && !embedded}
<p class="ldp-empty" data-testid="ldp-empty">
  <span>{t('ledger.drawer.no_accounts')}</span>
  <a href={LEDGER_HASH} class="ldp-empty-link" onclick={openProviders}>{t('ledger.drawer.add_one')}</a>
</p>
{:else}
<section class="ldp" data-fold={fold} data-embedded={embedded ? '1' : undefined} aria-labelledby="ldp-title">
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="ldp-head" onclick={onHeadClick}>
    <a
      href={LEDGER_HASH}
      class="ldp-title"
      id="ldp-title"
      role="button"
      onclick={onTitleClick}
      onkeydown={onTitleKeydown}
    >{t('ledger.drawer.title')}</a>
    {#if fold !== 'hidden' && updated}
      <span class="ldp-dim">{updated}</span>
    {/if}
    <span class="ldp-auto"><AutoSwitchIcon /></span>
    <IconButton
      label={foldLabel(fold)}
      variant="quiet"
      data-ldp-toggle=""
      data-fold={fold}
      aria-expanded={fold === 'compact' || fold === 'expanded'}
      aria-controls={fold === 'compact' || fold === 'expanded' ? 'ldp-accounts' : undefined}
      onclick={toggle}
    >
      <Icon name="chevron-right" size={12} strokeWidth={2} />
    </IconButton>
  </div>

  {#if notice}<p class="ldp-notice">{notice}</p>{/if}
  {#if fold === 'hidden' && totalBars.length}
    <div class="ldp-total" data-ledger-total>
      <div class="ldp-total-head">
        <span class="ldp-total-label">{t('ledger.total.label')}</span>
        <span class="ldp-dim">{t('ledger.total.accounts', { count: snapshot?.total?.accounts ?? 0 })}</span>
      </div>
      <div class="ldp-mini">
        {#each totalBars as b (b.key)}
          <span class="ldp-meter">
            <span class="ldp-dim">{b.label}</span>
            {@render bar(b, 7, staleRead)}
            <span class="ldp-pct">{b.percentText}</span>
          </span>
        {/each}
      </div>
    </div>
  {:else if fold === 'glance'}
    <LedgerGlanceView {snapshot} {now} />
  {/if}

  {#if fold === 'compact' || fold === 'expanded'}
  {#if loopStopped}<p class="ldp-notice" data-tone="high">{loopStopped}</p>{/if}

  {#if accounts.length}
    <ul class="ldp-accounts" id="ldp-accounts" aria-label={t('ledger.drawer.list')}>
      {#each accounts as account (account.id)}
        {@const compact = fold === 'expanded' ? [] : compactBars(account)}
        <li
          class="ldp-account"
          data-pick={picked.has(account.id) ? '1' : '0'}
          data-stale={isStale(account) ? '1' : '0'}
          data-active-account={activeAccountId === account.id ? '1' : '0'}
        >
          <div class="ldp-row">
            <span class="ldp-id">
              <span class="ldp-provider-mark" aria-hidden="true">{@html providerMark(account.provider, 14).svg}</span>
              <span class="ldp-name">{nameOf(account)}</span>
              {#if fold === 'expanded'}
                <span class="ldp-plan">
                  {providerName(account.provider)}{#if account.plan}<span class="ldp-dot" aria-hidden="true"
                    ></span>{account.plan}{/if}
                </span>
              {/if}
              {#if picked.has(account.id)}
                <span
                  class="ldp-marker"
                  role="img"
                  aria-label={t('ledger.drawer.pick_marker')}
                  title={t('ledger.drawer.pick_marker')}
                >
                  <Icon name="star" fill="solid" size={13} />
                </span>
              {/if}
              {#if account.credential_state !== 'ok' && account.credential_state !== 'missing'}
                <Tag tone={TAG_TONE[credentialTone(account.credential_state)] ?? 'neutral'}>{credentialLabel(account.credential_state, t)}</Tag>
              {/if}
              {#if needsReadd(account)}
                <a
                  class="ldp-readd"
                  href={ledgerAccountHash(account.id)}
                  onclick={(event) => readd(event, account.id)}>{t(account.credential_state === 'missing' ? 'ledger.drawer.sign_in' : 'ledger.drawer.readd')}</a
                >
              {/if}
              
              {#if isStale(account) && fold !== 'compact'}
                <Tag tone="warn">{t('ledger.drawer.stale')}</Tag>
              {/if}
              <span
                class="ldp-open-count"
                data-open-count={openCounts.get(account.id)?.length ?? 0}
                data-tooltip={t('ledger.sessions.count', { count: openCounts.get(account.id)?.length ?? 0 })}
                aria-label={t('ledger.sessions.count', { count: openCounts.get(account.id)?.length ?? 0 })}
                ><Icon name="terminal" size={11} strokeWidth={1.75} /><span class="ldp-open-n">{openCounts.get(account.id)?.length ?? 0}</span></span
              >
              <SwitchAccountButton {account} />
            </span>
          </div>
          {#if compact.length}
            <div class="ldp-mini">
              {#each compact as b (b.key)}
                <span class="ldp-meter">
                  <span class="ldp-dim">{b.label}</span>
                  {@render bar(b, 7, isStale(account))}
                  <span class="ldp-pct">{b.percentText}</span>
                </span>
              {/each}
            </div>
          {/if}
          {#if fold === 'expanded'}
            {#each bars(account) as b (b.key)}
              <div class="ldp-window">
                {@render bar(b, 8, isStale(account))}
                <div class="ldp-caption">
                  <span>{b.label}</span>
                  <span class="ldp-reset">{b.resetText}</span>
                  <span class="ldp-pct">{b.percentText}</span>
                </div>
              </div>
            {/each}
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
  {/if}
</section>
{/if}

<style>
  @layer components {
    .ldp {
      --ldp-step: calc(var(--oc-gutter) / 3);
      margin: 0 var(--oc-space-2);
      padding: var(--oc-space-1) var(--oc-space-2) var(--oc-space-2);
      border: var(--oc-border) solid var(--oc-line-frame);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      line-height: 1.35;
    }

    .ldp[data-embedded] {
      margin: 0;
      border: 0;
      height: 100%;
      overflow-y: auto;
      box-sizing: border-box;
    }

    .ldp-head,
    .ldp-id,
    .ldp-caption {
      display: flex;
      align-items: center;
      gap: var(--oc-space-1-5);
      min-width: 0;
    }

    .ldp-title {
      display: inline-flex;
      align-items: center;
      padding: var(--oc-space-0-5) var(--oc-space-1);
      margin: calc(var(--oc-space-0-5) * -1) calc(var(--oc-space-1) * -1);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-primary);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      text-decoration: none;
      cursor: pointer;
      transition: background 120ms ease;
    }

    .ldp-title:hover {
      background: var(--oc-ground-hover);
    }

    .ldp-dim {
      color: var(--oc-text-dim);
    }

    .ldp-provider-mark {
      display: inline-flex;
      flex: none;
      align-items: center;
    }

    .ldp-plan {
      flex-shrink: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--oc-text-dim);
    }

    .ldp-auto {
      display: inline-flex;
      margin-left: auto;
    }

    .ldp-auto + :global([data-ldp-toggle]) {
      margin-left: 0;
    }

    :global([data-ldp-toggle]) {
      --oc-ibtn-size: 20px;
      width: auto;
      min-width: var(--oc-ibtn-size);
      margin-left: auto;
      flex-shrink: 0;
      color: var(--oc-text-muted);
    }
    :global([data-ldp-toggle]:hover:not(:disabled)) {
      color: var(--oc-text-primary);
    }
    :global([data-ldp-toggle] svg) {
      transition: transform 140ms ease;
    }

    :global([data-ldp-toggle][data-fold='expanded'] svg) {
      transform: rotate(90deg);
    }

    :global([data-ldp-toggle][data-fold='hidden'] svg) {
      transform: rotate(-90deg);
    }

    :global([data-ldp-toggle][data-fold='glance'] svg) {
      transform: rotate(180deg);
    }

    .ldp-total {
      margin-top: var(--oc-space-1);
      padding-top: calc(var(--ldp-step) * 2);
      border-top: var(--oc-border) solid var(--oc-line-faint);
    }

    .ldp-total-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--oc-space-2);
      min-width: 0;
    }

    .ldp-total-label {
      color: var(--oc-text-primary);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .ldp-empty {
      margin: 0;
      padding: var(--oc-space-1) var(--oc-space-2);
      border: var(--oc-border) solid var(--oc-line-frame);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      line-height: 1.35;
    }

    .ldp-empty-link {
      color: var(--oc-orange);
      text-decoration: none;
    }

    .ldp-empty-link:hover {
      text-decoration: underline;
    }

    .ldp-notice {
      margin: calc(var(--ldp-step) * 2) 0 0;
      overflow-wrap: anywhere;
    }

    .ldp-notice[data-tone='high'] {
      color: var(--oc-coral);
    }

    .ldp-accounts {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      --ldp-row-gap: calc(var(--ldp-step) * 3);
      gap: calc((var(--ldp-row-gap) - var(--oc-border)) / 2);
      margin: var(--oc-space-1) 0 0;
      padding: calc(var(--ldp-step) * 3) 0 0;
      list-style: none;
      border-top: var(--oc-border) solid var(--oc-line-faint);
    }

    .ldp[data-fold='expanded'] .ldp-accounts {
      --ldp-row-gap: calc(var(--ldp-step) * 4);
    }

    .ldp-account + .ldp-account {
      border-top: var(--oc-border) solid var(--oc-line-faint);
      padding-top: calc((var(--ldp-row-gap) - var(--oc-border)) / 2);
    }

    .ldp-account {
      padding-left: calc(var(--ldp-step) * 1.5);
      padding-right: calc(var(--ldp-step) * 1.5);
      margin-left: calc(var(--ldp-step) * -1.5);
      margin-right: calc(var(--ldp-step) * -1.5);
    }

    .ldp-account[data-active-account='1'] .ldp-name {
      font-weight: bold;
    }

    .ldp-open-count {
      display: inline-flex;
      flex: 0 0 auto;
      align-items: center;
      gap: calc(var(--oc-space-1) * 0.75);
      box-sizing: border-box;
      padding: var(--oc-border) var(--oc-space-1);
      border: var(--oc-border) solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro, 10px);
      line-height: 1;
    }

    .ldp-open-n {
      font-variant-numeric: tabular-nums;
      color: var(--oc-text-secondary);
      text-box: trim-both cap alphabetic;
    }

    .ldp-name {
      min-width: 0;
      flex: 0 1 auto;
      overflow: clip;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--oc-text-primary);
      text-box: trim-both cap alphabetic;
      padding-block: 0.3em;
      margin-block: -0.3em;
    }

    .ldp-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
    }

    .ldp-mini {
      display: flex;
      gap: calc(var(--ldp-step) * 3);
      margin-top: calc(var(--ldp-step) * 1.5);
    }

    .ldp-meter {
      flex: 1 1 0;
      min-width: 0;
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
    }

    .ldp-marker {
      display: inline-flex;
      align-items: center;
      flex-shrink: 0;
      color: var(--oc-green-bright);
    }

    .ldp-marker :global(svg) {
      width: 1.1em;
      height: 1.1em;
    }

    .ldp-pct {
      flex-shrink: 0;
      min-width: 4ch;
      text-align: right;
      font-variant-numeric: tabular-nums;
    }

    .ldp-dot::before {
      content: '\00b7';
      padding: 0 var(--oc-space-1);
    }

    .ldp-window {
      margin-top: calc(var(--ldp-step) * 2);
    }

    .ldp-reset {
      margin-right: auto;
      color: var(--oc-text-dim);
    }

    .ldp-readd {
      flex-shrink: 0;
      color: var(--oc-cyan);
      font-size: var(--oc-fs-micro);
      text-decoration: underline;
      text-underline-offset: 2px;
      border-radius: var(--oc-radius-sm);
    }

    .ldp-readd:hover {
      color: var(--oc-text-primary);
    }


    @media (max-width: 640px) {
      .ldp {
        margin: var(--oc-space-1) var(--oc-space-1-5);
        padding: var(--oc-space-1-5);
      }
    }
  }
</style>
