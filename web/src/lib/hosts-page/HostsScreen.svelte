<!-- the detail pane -->
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import ManagerFrame from '../manager-frame/ManagerFrame.svelte';
    import { createManagerController } from '../manager-frame/manager-controller.svelte';
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import type { ManagerAdapter, ManagerItem } from '../manager-frame/types';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { openModal } from '../modal';
    import { openSession } from '../../opscenter/api/host';
    import Check from '../../opscenter/ui/Check.svelte';
    import AddHostModal from './AddHostModal.svelte';
    import FedConfirmModal from './FedConfirmModal.svelte';
    import { createFederationApi, type DiscoveredMac, type FederationApi, type PeerRow } from './federation-api';
    import {
        createHostsAdapter,
        createHostsApi,
        FOUND_GROUP,
        foundStateLabel,
        probeVerdict,
        type HostItem,
        type HostRow,
        type HostsApi,
    } from './hosts-adapter';
    import PairModal from './PairModal.svelte';
    import PeerDetail from './PeerDetail.svelte';
    import PeerState from './PeerState.svelte';
    import ShowCodeModal from './ShowCodeModal.svelte';

    interface Props {
        adapter?: ManagerAdapter;
        api?: HostsApi;
        fed?: FederationApi;
        t?: Translate;
        embedded?: boolean;
        view?: 'machines' | 'pairing';
        hideFids?: ReadonlySet<string>;
    }

    const { adapter, api, fed, t = appT, embedded = false, view, hideFids }: Props = $props();

    // svelte-ignore state_referenced_locally
    const fedCalls: FederationApi = fed ?? createFederationApi();
    // svelte-ignore state_referenced_locally
    const ctl = createManagerController(adapter ?? createHostsAdapter(t, undefined, fedCalls), t(MANAGER_KEYS.errorTitle));
    // svelte-ignore state_referenced_locally
    const calls: HostsApi = api ?? createHostsApi();

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let query = $state('');
    let selectedId = $state<string | null>(null);
    let probing = $state<string | null>(null);
    let notice = $state<{ id: string; text: string; error: boolean } | null>(null);

    let advertise = $state<boolean | null>(null);
    let advertiseBusy = $state(false);
    let toolNotice = $state<{ text: string; error: boolean } | null>(null);

    async function loadSettings(): Promise<void> {
        try {
            advertise = (await fedCalls.settings()).advertise;
        } catch {
            advertise = null;
        }
    }

    // svelte-ignore state_referenced_locally
    if (embedded) {
        void ctl.load();
        void loadSettings();
    }

    export function show(): void {
        if (open) return;
        opener = captureOpener();
        open = true;
        void ctl.load();
        void loadSettings();
    }

    export function close(): void {
        if (!open || embedded) return;
        open = false;
        selectedId = null;
        notice = null;
        restoreOpenerFocus(opener);
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    async function addOne(): Promise<void> {
        const row = await openModal<HostRow, { api: HostsApi; t: Translate }>(AddHostModal, { api: calls, t });
        if (!row) return;
        await ctl.load();
        selectedId = row.key;
    }

    async function pairOne(found: DiscoveredMac | null): Promise<void> {
        const peer = await openModal<PeerRow, { fed: FederationApi; t: Translate; found: DiscoveredMac | null }>(PairModal, { fed: fedCalls, t, found });
        if (!peer) return;
        await ctl.load();
        selectedId = peer.key;
    }

    function openPeerSession(sessionId: string, tmuxName: string): void {
        close();
        openSession(sessionId, tmuxName);
    }

    async function showCode(): Promise<void> {
        await openModal<null, { fed: FederationApi; t: Translate }>(ShowCodeModal, { fed: fedCalls, t });
    }

    async function toggleAdvertise(next: boolean): Promise<void> {
        advertiseBusy = true;
        try {
            advertise = (await fedCalls.setAdvertise(next)).advertise;
            toolNotice = null;
        } catch (err) {
            toolNotice = { text: t('hosts.fed.action_failed', { reason: err instanceof Error ? err.message : '' }), error: true };
        } finally {
            advertiseBusy = false;
        }
    }

    async function rotateKey(): Promise<void> {
        const yes = await openModal<true, { title: string; body: string; confirmLabel: string; t: Translate }>(FedConfirmModal, {
            title: t('hosts.rotate.title'),
            body: t('hosts.rotate.body'),
            confirmLabel: t('hosts.rotate.confirm'),
            t,
        });
        if (!yes) return;
        try {
            const result = await fedCalls.rotate();
            toolNotice = { text: t('hosts.rotate.done', { fid: result.fid, announced: result.announced, missed: result.not_announced }), error: false };
            await ctl.load();
        } catch (err) {
            toolNotice = { text: t('hosts.fed.action_failed', { reason: err instanceof Error ? err.message : '' }), error: true };
        }
    }

    const pairingView = $derived(view !== 'machines');
    const machinesView = $derived(view !== 'pairing');
    const shownItems = $derived(
        (view ? ctl.items.filter((item) => ((item as HostItem).group === FOUND_GROUP) === (view === 'pairing')) : ctl.items).filter(
            (item) => !((item as HostItem).kind === 'peer' && hideFids?.has((item as HostItem).peer?.fid ?? '')),
        ),
    );

    const groups = $derived([...new Set(shownItems.map((item) => (item as HostItem).group))]);

    function groupTitle(id: string, members: readonly ManagerItem[]): string {
        if (id === FOUND_GROUP) return t('hosts.found.group');
        const rows = members as readonly HostItem[];
        return (rows.find((m) => m.kind === 'peer') ?? rows[0])?.name ?? id;
    }

    function groupMeta(id: string, members: readonly ManagerItem[]): string {
        if (id === FOUND_GROUP) return t('hosts.found.group_meta', { count: members.length });
        const kinds = new Set((members as readonly HostItem[]).map((m) => m.kind));
        return [kinds.has('ssh') ? t('hosts.group.ssh') : '', kinds.has('peer') ? t('hosts.group.peer') : ''].filter(Boolean).join(' + ');
    }

    async function probeOne(key: string): Promise<void> {
        if (probing) return;
        probing = key;
        try {
            const row = await calls.probe(key);
            await ctl.load();
            notice = { id: key, text: t('hosts.page.probe_done', { verdict: probeVerdict(row.probe_state, t) }), error: row.probe_state !== 'ok' };
        } catch (err) {
            notice = { id: key, text: t('hosts.page.probe_failed', { reason: err instanceof Error ? err.message : '' }), error: true };
        } finally {
            probing = null;
        }
    }
</script>

{#if open}
    <ManagerFrame
        title={t('hosts.page.title')}
        label={t('hosts.page.label')}
        items={shownItems}
        status={ctl.status}
        {query}
        onQuery={(next) => (query = next)}
        layout="list"
        {selectedId}
        onSelect={(id) => {
            selectedId = id;
            notice = null;
        }}
        onToggle={(id, next) => void ctl.toggle(id, next)}
        toggles={ctl.toggles}
        onRetry={() => void ctl.load()}
        onRemove={(id) => void ctl.remove(id)}
        itemActions={ctl.actions}
        removed={ctl.removed}
        {groups}
        groupOf={(item) => (item as HostItem).group}
        onInstall={machinesView ? () => void addOne() : undefined}
        installLabel={t('hosts.page.add')}
        onClose={embedded ? undefined : close}
        emptyText={t(view === 'pairing' ? 'hosts.found.empty' : 'hosts.page.empty')}
        {embedded}
        {t}
    >
        {#snippet actions()}
            <button type="button" class="oc-btn" data-host-pair onclick={() => void pairOne(null)}>{t('hosts.fed.pair')}</button>
            {#if pairingView}
                <button type="button" class="oc-btn" data-host-show-code onclick={() => void showCode()}>{t('hosts.fed.show_code')}</button>
            {/if}
        {/snippet}
        {#snippet toolbar()}
            {#if pairingView && advertise !== null}
                <Check
                    role="switch"
                    label={t(advertise ? 'hosts.fed.advertise_on' : 'hosts.fed.advertise_off')}
                    checked={advertise}
                    disabled={advertiseBusy}
                    ariaLabel={t('hosts.fed.advertise')}
                    data-host-advertise="on"
                    onToggle={(next) => void toggleAdvertise(next)}
                />
            {/if}
            {#if pairingView}
                <button type="button" class="oc-btn oc-btn--ghost" data-host-rescan onclick={() => void ctl.load()}>{t('hosts.fed.rescan')}</button>
                <button type="button" class="oc-btn oc-btn--danger host-rotate" data-host-rotate onclick={() => void rotateKey()}>{t('hosts.fed.rotate')}</button>
            {/if}
            {#if toolNotice}
                <span class={toolNotice.error ? 'host-detail__error' : 'host-detail__notice'} role={toolNotice.error ? 'alert' : 'status'} data-host-tool-notice>{toolNotice.text}</span>
            {/if}
        {/snippet}
        {#snippet groupHead(id, members)}
            <div class="oc-page__group-head" data-host-group-head={id}>
                <h2 class="oc-page__group-title">{groupTitle(id, members)}</h2>
                <span class="oc-page__group-meta">{groupMeta(id, members)}</span>
            </div>
        {/snippet}
        {#snippet cardExtra(item)}
            {@const hi = item as HostItem}
            {#if hi.peer}
                <span class="host-row-extra mgr-card__aside">
                    {#if hi.row && !hi.row.local}<code data-host-target>{hi.row.ssh_target}</code>{/if}
                    <PeerState state={hi.peer.state} {t} />
                </span>
            {/if}
        {/snippet}
        {#snippet detail(item)}
            {@const hi = item as HostItem}
            {@const row = hi.row}
            {#if hi.peer}
                <PeerDetail peer={hi.peer} fed={fedCalls} {t} onChanged={() => { selectedId = null; void ctl.load(); }} onOpen={openPeerSession} />
            {:else if hi.found}
                <dl class="mgr-facts">
                    <dt>{t('hosts.found.fact.host')}</dt>
                    <dd>{hi.found.host}:{hi.found.port}</dd>
                    <dt>{t('hosts.found.fact.fid')}</dt>
                    <dd>{hi.found.fid}</dd>
                    <dt>{t('hosts.found.fact.state')}</dt>
                    <dd data-found-state={hi.found.state}>{foundStateLabel(hi.found.state, t)}</dd>
                </dl>
                <button type="button" class="oc-btn oc-btn--confirm" data-found-pair onclick={() => void pairOne(hi.found)}>{t('hosts.found.pair')}</button>
            {:else if row}
            <dl class="mgr-facts">
                <dt>{t('hosts.page.fact.key')}</dt>
                <dd class="host-detail__key">{row.key}</dd>
                {#if !row.local}
                    <dt>{t('hosts.page.fact.target')}</dt>
                    <dd>{row.ssh_target}</dd>
                    {#if row.ssh_port}
                        <dt>{t('hosts.page.fact.port')}</dt>
                        <dd>{row.ssh_port}</dd>
                    {/if}
                    <dt>{t('hosts.page.fact.socket')}</dt>
                    <dd>{row.socket}</dd>
                {/if}
                <dt>{t('hosts.page.fact.sessions')}</dt>
                <dd data-host-session-count>{row.session_count}</dd>
                {#if !row.local}
                    <dt>{t('hosts.page.fact.probe_state')}</dt>
                    <dd data-host-probe-state={row.probe_state}>{probeVerdict(row.probe_state, t)}</dd>
                {/if}
                {#if row.probe_detail}
                    <dt>{t('hosts.page.fact.probe_detail')}</dt>
                    <dd>{row.probe_detail}</dd>
                {/if}
                {#if row.probed_at}
                    <dt>{t('hosts.page.fact.probed_at')}</dt>
                    <dd>{row.probed_at}</dd>
                {/if}
                {#if row.tmux_version}
                    <dt>{t('hosts.page.fact.tmux_version')}</dt>
                    <dd>{row.tmux_version}</dd>
                {/if}
                {#if row.login_shell}
                    <dt>{t('hosts.page.fact.login_shell')}</dt>
                    <dd>{row.login_shell}</dd>
                {/if}
                {#if row.machine_id}
                    <dt>{t('hosts.page.fact.machine_id')}</dt>
                    <dd>{row.machine_id}</dd>
                {/if}
                {#if row.remote_carnivore}
                    <dt>{t('hosts.page.fact.remote_carnivore')}</dt>
                    <dd>{row.remote_carnivore}</dd>
                {/if}
            </dl>
            {#if !row.local}
                <button
                    type="button"
                    class="oc-btn"
                    data-host-probe-button
                    disabled={probing === row.key}
                    onclick={() => void probeOne(row.key)}
                    >{probing === row.key ? t('hosts.page.probe_button_busy') : t('hosts.page.probe_button')}</button
                >
            {/if}
            {#if notice && notice.id === row.key}
                <p class={notice.error ? 'host-detail__error' : 'host-detail__notice'} role={notice.error ? 'alert' : 'status'} data-host-probe-notice>{notice.text}</p>
            {/if}
            {/if}
        {/snippet}
    </ManagerFrame>
{/if}

<style>
    .host-rotate {
        margin-left: auto;
    }

    .host-row-extra {
        display: inline-flex;
        align-items: center;
        gap: var(--oc-space-2);
    }

    .host-detail__key {
        color: var(--pl-muted);
    }

    .host-detail__notice,
    .host-detail__error {
        margin: 8px 0 0;
        padding: 6px 8px;
        border-left: 2px solid var(--oc-cyan);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        font-size: 12px;
        overflow-wrap: anywhere;
    }

    .host-detail__error {
        border-left-color: var(--oc-coral);
    }
</style>
