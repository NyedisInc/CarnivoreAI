
<script lang="ts">
    import { onDestroy } from 'svelte';
    import { t as reactiveT, authFetch, openModal, resourcePush, failureReason, type Translate } from '../sdk';
    import { Button, Field, State, Switch } from '../sdk/ui';
    import RolloutModal from './RolloutModal.svelte';
    import TetheredRow from './TetheredRow.svelte';
    import type { RolloutPreview } from './rollout-model';
    import ArgentBudgetPanel from './ArgentBudgetPanel.svelte';
    import ArgentWriteback from './ArgentWriteback.svelte';
    import ClassifierChange from './ClassifierChange.svelte';
    import RetagDialog from './RetagDialog.svelte';
    import OutageBanner from './OutageBanner.svelte';

    interface Status {
        feature_on: boolean;
        settings: { server_url: string; gateway_url: string; ca_path: string; enabled: boolean; refuse_direct_launch: boolean };
        state: string;
        refusal: { code: string; message: string } | null;
        login: { state: string; display_name: string; flow: { state: string; user_code?: string; verification_uri?: string; reason?: string } };
    }

    interface Props {
        t?: Translate;
        fetcher?: typeof authFetch;
        pollMs?: number;
    }
    const { t = reactiveT, fetcher = authFetch, pollMs = 30000 }: Props = $props();

    const ROUTE = '/argent';
    const STATES = ['up', 'down', 'unsupported', 'cap_too_low', 'login_expired', 'unknown'];
    const LOGINS = ['logged_out', 'logged_in', 'login_soon', 'login_expired', 'pending'];

    let status = $state<Status | null>(null);
    let busy = $state(false);
    let problem = $state('');
    let server = $state('');
    let gateway = $state('');
    let caPath = $state('');
    let edited = $state(false);
    let preview = $state<RolloutPreview | null>(null);

    const phase = $derived(status ? (STATES.includes(status.state) ? status.state : 'unknown') : '');
    const login = $derived(status ? (LOGINS.includes(status.login.state) ? status.login.state : 'logged_out') : '');
    const flow = $derived(status?.login.flow);
    const loggedIn = $derived(login === 'logged_in' || login === 'login_soon');

    function take(next: Status): void {
        status = next;
        if (!edited) {
            server = next.settings.server_url;
            gateway = next.settings.gateway_url;
            caPath = next.settings.ca_path;
        }
    }

    async function load(): Promise<void> {
        try {
            take(await fetcher<Status>(`${ROUTE}/status`));
            problem = '';
        } catch (error) {
            problem = failureReason(error);
        }
    }
    async function loadPreview(): Promise<void> {
        try {
            const next = await fetcher<RolloutPreview>(`${ROUTE}/rollout/preview`);
            preview = next.enabled ? next : null;
        } catch {
            preview = null;
        }
    }
    const refresh = () => { void load(); void loadPreview(); };
    refresh();
    const stop = resourcePush().pushOrPoll(refresh, pollMs, ['argent_status', 'argent_rollout']);
    onDestroy(stop);

    async function review(): Promise<void> {
        await openModal(RolloutModal, { t, fetcher });
        refresh();
    }

    async function act(path: string, init: { method: string; body?: string }): Promise<void> {
        busy = true;
        problem = '';
        try {
            await fetcher<unknown>(`${ROUTE}${path}`, init);
            await load();
        } catch (error) {
            problem = failureReason(error);
        } finally {
            busy = false;
        }
    }

    const put = (body: Record<string, unknown>) => act('/settings', { method: 'PUT', body: JSON.stringify(body) });
    const flip = async (next: boolean): Promise<void> => {
        await put({ enabled: next });
        if (status?.settings.enabled === next) await review();
    };
    const saveAddresses = () => put({ server_url: server, gateway_url: gateway, ca_path: caPath }).then(() => (edited = false));
    const openInBrowser = async (url: string) => {
        try {
            await fetcher('/browsers/open', { method: 'POST', body: JSON.stringify({ url, title: t('argent.shell.login.page_title') }) });
        } catch (error) {
            problem = failureReason(error);
        }
    };
</script>

<div class="tm" data-argent="panel">
    <p class="tm__sub">{t('argent.shell.intro')}</p>
    {#if status}
        <Switch label={t('argent.shell.switch')} hint={t('argent.shell.switch_hint')}
            bind:checked={() => status?.settings.enabled ?? false, (next) => void flip(next)}
            disabled={busy || !status.feature_on} data-argent="switch" />

        <form onsubmit={(event) => { event.preventDefault(); void saveAddresses(); }}>
            <Field label={t('argent.shell.server_url')} help={t('argent.shell.server_url_hint')} bind:value={server} oninput={() => (edited = true)}
                disabled={busy} spellcheck={false} autocomplete="off" autocapitalize="off" data-argent="server-url" />
            <Field label={t('argent.shell.gateway_url')} help={t('argent.shell.gateway_url_hint')} bind:value={gateway} oninput={() => (edited = true)}
                disabled={busy} spellcheck={false} autocomplete="off" autocapitalize="off" data-argent="gateway-url" />
            <Field label={t('argent.shell.ca_path')} help={t('argent.shell.ca_path_hint')} bind:value={caPath} oninput={() => (edited = true)}
                disabled={busy} spellcheck={false} autocomplete="off" autocapitalize="off" data-argent="ca-path" />
            <div class="tm__actions">
                <Button type="submit" variant="confirm" size="sm" disabled={busy || !edited} data-argent="save">{t('argent.shell.save')}</Button>
            </div>
        </form>

        <p class="tm__sub" role="status" data-argent="login">
            {t(`argent.shell.login.${login}`, { name: status.login.display_name })}
        </p>
        {#if login === 'pending' && flow?.user_code && flow.verification_uri}
            <p class="tm__sub" data-argent="code">{t('argent.shell.login.code', { code: flow.user_code })}</p>
            <div class="tm__actions">
                <Button size="sm" variant="confirm" disabled={busy} data-argent="open" onclick={() => void openInBrowser(flow.verification_uri ?? '')}>
                    {t('argent.shell.login.open')}
                </Button>
                <a href={flow.verification_uri} target="_blank" rel="noopener noreferrer" data-argent="link">{t('argent.shell.login.link')}</a>
            </div>
        {/if}
        {#if flow && ['expired', 'denied', 'failed'].includes(flow.state)}
            <State kind="warn" inline title={t(`argent.shell.login.flow.${flow.state}`)} data-argent="flow" />
        {/if}
        <div class="tm__actions">
            {#if login !== 'pending'}
                <Button size="sm" disabled={busy || !status.feature_on || !status.settings.server_url} data-argent="log-in"
                    onclick={() => void act('/login/start', { method: 'POST' })}>
                    {t(login === 'logged_out' ? 'argent.shell.login.start' : 'argent.shell.login.again')}
                </Button>
            {/if}
            {#if loggedIn || login === 'login_expired' || login === 'pending'}
                <Button size="sm" variant="danger" disabled={busy} data-argent="log-out" onclick={() => void act('/login', { method: 'DELETE' })}>
                    {t(login === 'pending' ? 'argent.shell.login.cancel' : 'argent.shell.login.stop')}
                </Button>
            {/if}
        </div>

        <OutageBanner {t} {fetcher} {pollMs} />
        <TetheredRow {preview} onreview={() => void review()} {t} />

        <p class="tm__sub" role="status" data-argent="state">{t(`argent.shell.state.${phase}`)}</p>
        {#if status.refusal}
            <p class="tm__sub" data-argent="refusal">{t(`argent.shell.refusal.${status.refusal.code}`)}</p>
        {/if}

        <Switch label={t('argent.shell.refuse_direct')} hint={t('argent.shell.refuse_direct_hint')}
            bind:checked={() => status?.settings.refuse_direct_launch ?? false, (next) => void put({ refuse_direct_launch: next })}
            disabled={busy} data-argent="refuse-direct" />
        <ArgentBudgetPanel {t} {fetcher} {pollMs} />
        <ArgentWriteback {t} {fetcher} {pollMs} />
        <ClassifierChange {t} {fetcher} />
        <RetagDialog {t} {fetcher} />
        <p class="tm__sub" data-argent="disclosure">{t('argent.shell.disclosure')}</p>
    {:else if !problem}
        <p class="tm__sub">{t('argent.shell.loading')}</p>
    {/if}
    {#if problem}<State kind="error" inline title={problem} data-argent="problem" />{/if}
</div>
