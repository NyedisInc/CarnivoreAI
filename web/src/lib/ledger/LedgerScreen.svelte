<!-- display: none -->
<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import './ledger-chrome.css';
    import LedgerCards from './LedgerCards.svelte';
    import LedgerHeadroom from './LedgerHeadroom.svelte';
    import LedgerAddButton from './LedgerAddButton.svelte';
    import Page from '../../opscenter/ui/Page.svelte';
    import LedgerTotal from './LedgerTotal.svelte';
    import AutoSwitchPanel from '../account-switch/AutoSwitchPanel.svelte';
    import { accountSwitch } from '../account-switch/switch-store.svelte';
    import LedgerAccountsEditor from './LedgerAccountsEditor.svelte';
    import LedgerNotices from './LedgerNotices.svelte';
    import LedgerPeers from './LedgerPeers.svelte';
    import LedgerSessions from './LedgerSessions.svelte';
    import { groupSessionsByAccount, type ProviderSession } from './ledger-sessions';
    import { sessions } from '../../opscenter/api/sessions.svelte';
    import { openSession } from '../../opscenter/api/host';
    import { BUILTIN_RENAME_SETTLE_MS, browserLedgerHost, createLedgerPoller, type LedgerHost } from './ledger-host';
    import {
        LEDGER_KEYS,
        formatAge,
        isBuiltInLogin,
        sortAccounts,
        type PeersLedger,
        type ProviderLedger,
    } from './ledger-model';
    import { storedAccounts, type StoredAccount } from './accounts-model';
    import { mergeConfiguredRows } from './ledger-rows';
    import {
        removeRow,
        renameBuiltInLogin,
        saveRowEdit,
        startLogin,
        type RowActionDeps,
        type RowBusyKind,
    } from './row-actions';

    interface Props {
        host?: LedgerHost;
        t?: Translate;
        nowMs?: () => number;
        sessionRows?: () => readonly ProviderSession[];
        openRow?: (row: ProviderSession) => void;
    }

    const {
        host = browserLedgerHost(),
        t = reactiveT,
        nowMs = () => Date.now(),
        sessionRows = () => sessions.data ?? [],
        openRow = (row) => {
            close();
            openSession(row.session.id, row.tmux_session);
        },
    }: Props = $props();

    let open = $state(false);
    let loading = $state(false);
    let failure = $state<string | null>(null);
    let ledger = $state<ProviderLedger | null>(null);
    let peers = $state<PeersLedger | null>(null);
    // svelte-ignore state_referenced_locally
    let now = $state(nowMs());
    let opener: HTMLElement | null = null;
    /* could not */
    let configured = $state<readonly StoredAccount[] | null>(null);
    let busyRows = $state<Record<RowBusyKind, string | null>>({
        login: null,
        edit: null,
        remove: null,
    });
    /* could not */
    let rowNotices = $state<Record<string, string>>({});
    let targetId = $state<string | null>(null);
    let adding = $state(false);
    let root = $state<HTMLDivElement | undefined>();

    let pendingBuiltInName = $state<string | null>(null);
    let settleTimer: ReturnType<typeof setTimeout> | null = null;

    const taken = $derived(configured?.map((account) => account.id) ?? null);
    const rows = $derived(
        sortAccounts(mergeConfiguredRows(configured, ledger?.accounts ?? []), accountSwitch.data).map((row) =>
            pendingBuiltInName !== null && isBuiltInLogin(row)
                ? { ...row, name: pendingBuiltInName }
                : row,
        ),
    );
    const grouped = $derived(
        groupSessionsByAccount(
            sessionRows(),
            rows.map((row) => row.id),
        ),
    );
    const total = $derived(ledger?.total ?? null);
    const loop = $derived(ledger?.loop ?? null);
    const isEmpty = $derived(ledger !== null && failure === null && rows.length === 0);

    async function read(): Promise<void> {
        if (ledger === null) loading = true;
        const [measured, listed] = await Promise.allSettled([
            host.providerLedger(),
            host.listAccounts(),
        ]);
        if (measured.status === 'fulfilled') {
            ledger = measured.value;
            failure = null;
        } else {
            const error = measured.reason;
            failure = error instanceof Error ? error.message : String(error);
        }
        configured = listed.status === 'fulfilled' ? storedAccounts(listed.value) : null;
        loading = false;
        peers = (await host.peerLedger?.().catch(() => null)) ?? null;
        now = nowMs();
    }

    /* the built-in login */
    async function renameBuiltIn(row: { id: string }, label: string): Promise<boolean> {
        const landed = await renameBuiltInLogin(row.id, label, rowDeps);
        if (!landed) return false;
        pendingBuiltInName = label.trim() || null;
        if (settleTimer !== null) clearTimeout(settleTimer);
        settleTimer = setTimeout(() => {
            settleTimer = null;
            void read().then(() => {
                pendingBuiltInName = null;
            });
        }, BUILTIN_RENAME_SETTLE_MS);
        return true;
    }

    // svelte-ignore state_referenced_locally
    const rowDeps: RowActionDeps = {
        host,
        t,
        stored: (id) => configured?.find((account) => account.id === id) ?? null,
        busy: (kind, id) => {
            busyRows = { ...busyRows, [kind]: id };
        },
        isBusy: (kind) => busyRows[kind] !== null,
        notice: (id, message) => {
            const next = { ...rowNotices };
            if (message === null) delete next[id];
            else next[id] = message;
            rowNotices = next;
        },
        reread: () => read(),
        close: () => close(),
    };

    // svelte-ignore state_referenced_locally
    const poller = createLedgerPoller({
        tick: () => read(),
        isVisible: () => open,
    });

    export function show(account?: string): void {
        targetId = account || null;
        if (open) {
            void reveal();
            return;
        }
        const active = typeof document !== 'undefined' ? document.activeElement : null;
        opener = active instanceof HTMLElement ? active : null;
        open = true;
        now = nowMs();
        void read().then(reveal);
        poller.start();
    }

    async function reveal(): Promise<void> {
        if (!targetId) return;
        await tick();
        const card = [
            ...(root?.querySelectorAll<HTMLElement>('[data-ledger="row"][data-account-id]') ?? []),
        ].find((el) => el.dataset.accountId === targetId);
        if (!card) return;
        const control = card.querySelector<HTMLElement>('[data-ledger="login"], [data-ledger="edit-start"]');
        (control ?? card).scrollIntoView?.({ block: 'center', inline: 'nearest' });
        control?.focus({ preventScroll: true });
    }

    async function toggleAdd(): Promise<void> {
        adding = !adding;
        if (!adding) return;
        await tick();
        const field = root?.querySelector<HTMLElement>('#ledger-account-name');
        field?.scrollIntoView?.({ block: 'nearest' });
        field?.focus({ preventScroll: true });
    }

    /* nobody is looking at */
    export function close(): void {
        if (!open) return;
        open = false;
        targetId = null;
        adding = false;
        poller.stop();
        if (opener && typeof document !== 'undefined' && document.contains(opener)) {
            opener.focus();
        }
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    onMount(() => {
        return () => {
            poller.stop();
            if (settleTimer !== null) clearTimeout(settleTimer);
        };
    });
</script>

{#if open}
    {#snippet pageActions()}
        <LedgerAddButton {adding} onAdd={() => void toggleAdd()} {t} />
    {/snippet}

    <Page
        bind:root
        class="pledger"
        title={t(LEDGER_KEYS.screenTitle)}
        count={rows.length > 0 ? t(LEDGER_KEYS.totalAccounts, { count: rows.length }) : undefined}
        onClose={close}
        closeLabel={t(MANAGER_KEYS.close)}
        actions={pageActions}
    >
        
        <div class="oc-page__scroll">
            <div class="oc-page__main oc-page__main--stack">
                <LedgerNotices {loop} {failure} {loading} {isEmpty} {t} {now} />

                
                <LedgerAccountsEditor
                    {host}
                    {t}
                    {taken}
                    startOpen={isEmpty}
                    bind:open={adding}
                    onChanged={() => read()}
                />

                {#if rows.length}
                    <div class="ledger-deck">
                        <!-- running sessions -->
                        <AutoSwitchPanel />
                        {#if total}
                            <LedgerTotal {total} {now} {t} />
                        {/if}
                    </div>
                    <LedgerHeadroom accounts={rows} {t} />
                    <LedgerCards
                        accounts={rows}
                        {now}
                        {t}
                        onRemove={(row) => void removeRow(row.id, rowDeps)}
                        removingId={busyRows.remove}
                        onLogin={(row) => void startLogin(row.id, rowDeps)}
                        loginId={busyRows.login}
                        onEdit={(row, edit) => saveRowEdit(row.id, edit, rowDeps)}
                        editingId={busyRows.edit}
                        onRename={host.renameBuiltInLogin ? renameBuiltIn : undefined}
                        stored={(id) => configured?.find((account) => account.id === id) ?? null}
                        {rowNotices}
                        {targetId}
                        sessionsFor={(id) => grouped.byAccount.get(id) ?? []}
                        onOpenSession={openRow}
                    />
                    
                    <LedgerSessions
                        rows={grouped.unknown}
                        {t}
                        onOpen={openRow}
                        heading={t('ledger.sessions.unknown')}
                        hideEmpty
                    />
                {/if}

                {#if peers}
                    <LedgerPeers {peers} {now} {t} />
                {/if}

                
                {#if loop?.alive === true}
                    <footer class="ledger-foot">
                        <p class="ledger-loop" data-ledger="loop">
                            {t(LEDGER_KEYS.loopAlive, { age: formatAge(loop.last_pass_at, now, t) })}
                        </p>
                    </footer>
                {/if}
            </div>
        </div>
    </Page>
{/if}

<style>

    .ledger-deck {
        display: grid;
        grid-template-columns: minmax(0, 1fr);
        align-items: start;
        gap: var(--oc-space-4);
    }

    @container oc-pane (min-width: 820px) {
        .ledger-deck {
            grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
        }
    }

    .ledger-foot {
        padding-top: 10px;
        box-shadow: inset 0 var(--oc-border) 0 0 var(--oc-line-hairline);
    }

    .ledger-loop {
        margin: 0;
        font-size: var(--oc-fs-hint);
        color: var(--oc-text-muted);
    }
</style>
