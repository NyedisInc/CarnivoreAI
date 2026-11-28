<script lang="ts">
    import { onDestroy } from 'svelte';
    import { Button, Fold, State, Tag } from '../base';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { sessions } from '../../opscenter/api';
    import { openSession, primarySessionId } from '../../opscenter/api/host';
    import { startLiveTerminal, type LiveTerminal } from '../../opscenter/cells/terminal-live/client';
    import { bindTerminalTheme } from '../../opscenter/cells/terminal-live/theme';
    import { rowFor } from '../../opscenter/cells/terminal-viewer/meta';
    import { inputFocus } from '../../opscenter/lib/input-focus.svelte';
    import type { DevStatus, SessionStatus, StudioWorkspace, WorkspaceFile } from './types';
    import './plugin-studio.css';

    interface Props {
        workspace: StudioWorkspace;
        files: WorkspaceFile[];
        sessionStatus: SessionStatus;
        devStatus: DevStatus;
        busy?: boolean;
        paneVisible?: boolean;
        onStartDev: () => Promise<unknown>;
        onStopDev: () => Promise<unknown>;
        onRelaunchAgent: () => Promise<unknown>;
        t?: Translate;
    }

    const {
        workspace,
        files,
        sessionStatus,
        devStatus,
        busy = false,
        paneVisible = true,
        onStartDev,
        onStopDev,
        onRelaunchAgent,
        t = appT,
    }: Props = $props();

    let termHostEl = $state<HTMLDivElement | null>(null);
    let activeLive = $state<LiveTerminal | null>(null);

    const sessionId = $derived(sessionStatus.session_id ?? workspace.session_id ?? null);
    const slotId = $derived(sessionId ? `studio:${workspace.studio_id}:${sessionId}` : '');
    const hasTerminalRuntime = $derived(
        typeof globalThis !== 'undefined' &&
            typeof (globalThis as { CloudeTerminal?: { createTerminalClient?: unknown } }).CloudeTerminal
                ?.createTerminalClient === 'function',
    );
    const canAttachTerminal = $derived(Boolean(sessionId && sessionStatus.active && hasTerminalRuntime));

    function formatDevError(err: DevStatus['last_error']): string {
        if (!err) return '';
        if (typeof err === 'string') return err;
        const parts: string[] = [];
        if (typeof err.code === 'string' && err.code) parts.push(err.code);
        if (typeof err.detail === 'string' && err.detail) parts.push(err.detail);
        if (typeof err.path === 'string' && err.path) parts.push(err.path);
        if (Array.isArray(err.widened) && err.widened.length > 0) {
            parts.push(err.widened.map((item) => String(item)).join(', '));
        }
        if (parts.length > 0) return parts.join(' — ');
        try {
            return JSON.stringify(err);
        } catch {
            return String(err);
        }
    }

    let currentAttachedKey = '';
    let cleanupLive: (() => void) | null = null;

    function tearDownTerminal(): void {
        cleanupLive?.();
        cleanupLive = null;
        activeLive = null;
        currentAttachedKey = '';
    }

    $effect(() => {
        const host = termHostEl;
        const sid = sessionId;
        const slot = slotId;
        const attachable = canAttachTerminal;
        const row = sid ? rowFor(sessions.data, sid) : null;

        if (!host || !sid || !attachable) {
            tearDownTerminal();
            return;
        }

        const key = `${slot}:${row ? 'row' : 'stub'}`;
        if (key === currentAttachedKey) return;
        tearDownTerminal();

        const sessionArg = row ?? { id: sid, session: { id: sid } };
        const live = startLiveTerminal(host, slot, sessionArg);
        if (!live) return;

        currentAttachedKey = key;
        activeLive = live;

        const stopTheme = bindTerminalTheme(live.client, host, { pinnedTheme: null });
        const takeFocus = (): void => {
            inputFocus.claim(slot);
        };
        const dropFocus = (event: FocusEvent): void => {
            const next = event.relatedTarget;
            if (next instanceof Node && host.contains(next)) return;
            inputFocus.release(slot);
        };
        host.addEventListener('focus', takeFocus, true);
        host.addEventListener('focusin', takeFocus, true);
        host.addEventListener('keydown', takeFocus, true);
        host.addEventListener('pointerdown', takeFocus, true);
        host.addEventListener('focusout', dropFocus, true);

        cleanupLive = () => {
            host.removeEventListener('focus', takeFocus, true);
            host.removeEventListener('focusin', takeFocus, true);
            host.removeEventListener('keydown', takeFocus, true);
            host.removeEventListener('pointerdown', takeFocus, true);
            host.removeEventListener('focusout', dropFocus, true);
            stopTheme();
            live.dispose();
            inputFocus.release(slot);
        };
    });

    $effect(() => {
        const live = activeLive;
        const sid = sessionId;
        const visible = paneVisible;
        if (!live || !sid) return;
        const hidden = !visible || primarySessionId() === sid;
        const vote = (
            globalThis as {
                TerminalSizeVote?: { setTabHidden?: (client: unknown, hidden: boolean, doc?: Document) => void };
            }
        ).TerminalSizeVote;
        vote?.setTabHidden?.(live.client, hidden, typeof document !== 'undefined' ? document : undefined);
    });

    onDestroy(() => {
        tearDownTerminal();
    });
</script>

<div class="ps-pane">
    <div class="ps-pane__bar">
        <div class="ps-pane__controls">
            <h3 class="ps-pane__heading">{t('plugin_studio.terminal.heading')}</h3>
            {#if sessionStatus.active}
                <Tag tone="ok">{t('plugin_studio.terminal.session_active')}</Tag>
            {:else if sessionId}
                <Tag tone="neutral">{t('plugin_studio.terminal.session_inactive')}</Tag>
            {:else}
                <Tag tone="neutral">{t('plugin_studio.terminal.session_none')}</Tag>
            {/if}
            {#if devStatus.active}
                <Tag tone="ok">{t('plugin_studio.terminal.dev_active')}</Tag>
            {:else}
                <Tag tone="neutral">{t('plugin_studio.terminal.dev_stopped')}</Tag>
            {/if}
            {#if devStatus.lease}
                <Tag tone="info">
                    {t('plugin_studio.terminal.lease_badge')} · {devStatus.lease.baseline_sha.slice(0, 7)}
                </Tag>
            {/if}
            {#if devStatus.reload_count > 0}
                <Tag tone="neutral">
                    {t('plugin_studio.terminal.reloads', { count: devStatus.reload_count })}
                </Tag>
            {/if}
            {#if devStatus.last_reload_ms !== null}
                <Tag tone="neutral">
                    {t('plugin_studio.terminal.reload_ms', { ms: devStatus.last_reload_ms })}
                </Tag>
            {/if}
        </div>

        <div class="ps-pane__controls">
            {#if devStatus.active}
                <Button variant="secondary" disabled={busy} data-studio-dev-stop onclick={() => void onStopDev()}>
                    {t('plugin_studio.terminal.dev_stop')}
                </Button>
            {:else}
                <Button variant="confirm" disabled={busy} data-studio-dev-start onclick={() => void onStartDev()}>
                    {t('plugin_studio.terminal.dev_start')}
                </Button>
            {/if}
            <Button variant="quiet" disabled={busy} data-studio-relaunch onclick={() => void onRelaunchAgent()}>
                {t('plugin_studio.terminal.relaunch_agent')}
            </Button>
            {#if sessionId}
                <Button
                    variant="quiet"
                    data-studio-open-terminal
                    onclick={() => void openSession(sessionId, sessionStatus.tmux_session ?? workspace.session_tmux ?? null)}
                >
                    {t('plugin_studio.terminal.open_in_terminal')}
                </Button>
            {/if}
        </div>
    </div>

    {#if devStatus.last_error}
        <div class="ps-banner" role="alert" data-studio-dev-error>
            <p class="ps-banner__detail">{formatDevError(devStatus.last_error)}</p>
        </div>
    {/if}

    <div class="ps-terminal-wrap">
        {#if canAttachTerminal}
            <div class="ps-terminal-host" bind:this={termHostEl} data-studio-slot={slotId}></div>
        {:else}
            <div class="ps-terminal-fallback" data-studio-terminal-fallback>
                <State
                    kind="empty"
                    title={t('plugin_studio.terminal.fallback_title')}
                    hint={sessionId
                        ? t('plugin_studio.terminal.fallback_hint')
                        : t('plugin_studio.terminal.no_session_hint')}
                >
                    {#snippet actions()}
                        {#if sessionId}
                            <Button
                                variant="secondary"
                                data-studio-open-terminal-fallback
                                onclick={() => void openSession(sessionId, sessionStatus.tmux_session ?? workspace.session_tmux ?? null)}
                            >
                                {t('plugin_studio.terminal.open_in_terminal')}
                            </Button>
                        {:else}
                            <Button
                                variant="secondary"
                                disabled={busy}
                                data-studio-relaunch-fallback
                                onclick={() => void onRelaunchAgent()}
                            >
                                {t('plugin_studio.terminal.relaunch_agent')}
                            </Button>
                        {/if}
                    {/snippet}
                </State>
            </div>
        {/if}

        <div class="ps-terminal-files">
            <Fold label={`${t('plugin_studio.files.heading')} (${files.length})`} open={files.length > 0}>
                {#if files.length === 0}
                    <p class="ps-banner__detail">{t('plugin_studio.files.empty')}</p>
                {:else}
                    <div class="ps-file-list" data-studio-files>
                        {#each files as file (file.path)}
                            <div class="ps-file-row">
                                <span class="ps-file-row__path">{file.path}</span>
                                <span>
                                    {#if file.executable}
                                        <Tag tone="info">{t('plugin_studio.files.exec_badge')}</Tag>
                                    {/if}
                                    {file.size}B
                                </span>
                            </div>
                        {/each}
                    </div>
                {/if}
            </Fold>
        </div>
    </div>
</div>
