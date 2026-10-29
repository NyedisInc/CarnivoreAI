
<script lang="ts">
    import Button from '../base/Button.svelte';
    import SessionFace from '../sessions/SessionFace.svelte';
    import AgentFamilyPill from './AgentFamilyPill.svelte';
    import Glyph from '../Glyph.svelte';
    import IconButton from '../base/IconButton.svelte';
    import RunningSessionName from './RunningSessionName.svelte';
    import WrapperPill from './WrapperPill.svelte';
    import { launchedWithText } from './running-row';
    import { t as reactiveT } from '../i18n/index.svelte';
    import {
        RUNNING_SESSION_KEYS,
        relativeAge,
    } from '../../../../client/js/labels/running-session.js';
    import { sessionDisplayLabel } from '../sessions/session-label';
    import { runRowAction } from './running-actions';
    import {
        offersFork,
        renamePencilView,
        sessionRowId,
        themeCueView,
    } from './running-row';
    import type { RunningHost } from './running-host';
    import type { RunningSessionRow as Row, Translate } from '../sessions/types';

    interface Props {
        row: Row;
        host: RunningHost;
        nowMs?: number | null;
        t?: Translate;
    }

    let { row, host, nowMs = null, t = reactiveT }: Props = $props();

    let editing = $state(false);

    const owned = $derived(!!row.created_by_cloude);
    const displayName = $derived(sessionDisplayLabel(row));
    const pencil = $derived(renamePencilView(row));
    const rowId = $derived(sessionRowId(row));
    const launchedText = $derived(launchedWithText(row.launched_with, t));
    const theme = $derived(themeCueView(
        row.pinned_theme, (id) => host.themeColors(id),
    ));
    const menuTrigger = $derived(host.rowMenuTrigger(row, {
        renameable: pencil.state === 'renameable',
        reason: t(pencil.reasonKey),
    }));
    const actions = $derived(menuTrigger ? [] : host.actionsFor(row.status));
    const cardActions = $derived(host.cardActions(row.name, !!row.unread, row.status));
    const age = $derived(
        row.created_at_epoch
            ? relativeAge(row.created_at_epoch, t, nowMs ?? undefined)
            : null,
    );

    async function open(): Promise<void> {
        if (editing) return;
        if (row.is_active) {
            await host.returnToActive(row.session_id ?? null);
            return;
        }
        await host.attachSession(row.name);
    }

    function onKey(event: KeyboardEvent): void {
        if (event.target !== event.currentTarget) return;
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        void open();
    }

    function beginRename(event: Event): void {
        event.stopPropagation();
        if (pencil.state !== 'renameable') return;
        editing = true;
    }

    function swallow(event: Event): void {
        event.stopPropagation();
    }
</script>

<div
    class="running-session-row {owned ? 'owned' : 'external'}"
    data-name={row.name}
    data-active={row.is_active ? '1' : '0'}
    data-session-id={row.session_id ?? undefined}
    data-session-theme={theme ? theme.themeId : undefined}
    style={theme ? `--session-theme-accent: ${theme.accent};` : undefined}
    role="button"
    tabindex="0"
    onclick={open}
    onkeydown={onKey}
>
    <div class="running-session-top">
        <SessionFace {row} transport={host.transportFor(row.name) ?? null} />
        <RunningSessionName
            {displayName}
            renameKey={pencil.renameKey}
            {editing}
            onclose={() => { editing = false; }}
            {host}
            {t}
        />
        {#if theme}
            
            <span
                class="session-theme-swatch"
                role="img"
                aria-label={t(RUNNING_SESSION_KEYS.themeSwatch, { name: theme.name })}
                title={t(RUNNING_SESSION_KEYS.themeSwatch, { name: theme.name })}
            ></span>
        {/if}
        {#if pencil.state === 'renameable'}
            <span
                class="running-session-rename"
                role="button"
                tabindex="0"
                aria-label={t(pencil.reasonKey)}
                title={t(pencil.reasonKey)}
                data-rename-sid={pencil.renameKey}
                data-rename-name={row.name}
                onclick={beginRename}
                onkeydown={(event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return;
                    event.preventDefault();
                    beginRename(event);
                }}><Glyph name="pencil" /></span
            >
        {:else}
            
            
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <span
                class="running-session-rename-unavailable"
                aria-disabled="true"
                aria-label={t(pencil.reasonKey)}
                title={t(pencil.reasonKey)}
                onclick={swallow}><Glyph name="pencil" /></span
            >
        {/if}
        {#if offersFork(row)}
            <Button
                size="sm"
                data-fork-name={row.name}
                title={t(RUNNING_SESSION_KEYS.forkTitle)}
                aria-label={t(RUNNING_SESSION_KEYS.forkAria)}
                onclick={(event) => {
                    event.stopPropagation();
                    void host.forkSession(row.name);
                }}>{t(RUNNING_SESSION_KEYS.forkAction)}</Button
            >
        {/if}
        
        {#each cardActions as action (action.id)}
            <span
                class="mark-unread-toggle"
                class:mark-unread-toggle--active={row.unread}
                role="button"
                tabindex="0"
                aria-pressed={row.unread ? 'true' : 'false'}
                title={action.label}
                aria-label={action.label}
                data-mark-unread={row.name}
                data-row-menu-item={action.id}
                data-unread-current={row.unread ? 'true' : 'false'}
                onclick={(event) => {
                    event.stopPropagation();
                    void host.runCardAction(action.id, row.name, !!row.unread);
                }}
                onkeydown={(event) => {
                    if (event.key !== 'Enter' && event.key !== ' ') return;
                    event.preventDefault();
                    event.stopPropagation();
                    void host.runCardAction(action.id, row.name, !!row.unread);
                }}
                ><Glyph name={row.unread ? 'envelope-filled' : 'envelope-outline'} /></span
            >
        {/each}
        
        {#if menuTrigger}
            
            {@html menuTrigger}
        {/if}
        {#each actions as action (action.id)}
            
            <IconButton
                label={t(action.labelKey)}
                variant={action.id === 'restart' ? 'quiet' : 'danger'}
                data-session-action={action.id}
                data-session-name={row.name}
                onclick={(event) => {
                    event.stopPropagation();
                    void runRowAction(row, action.id, host, t);
                }}><Glyph name={action.glyph} /></IconButton
            >
        {/each}
    </div>
    <div class="running-session-badges">
        <span class="badge {owned ? 'badge-tmux' : 'badge-external'}"
            >{owned
                ? t(RUNNING_SESSION_KEYS.badgeTmux)
                : t(RUNNING_SESSION_KEYS.badgeExternal)}</span
        >
        <AgentFamilyPill
            family={row.agent_family}
            source={row.agent_family_source}
            {t}
        />
        <WrapperPill label={row.agent_wrapper_label} {t} />
        {#if launchedText}<span class="launched-with" data-launched-with>{launchedText}</span>{/if}
        {#if age}
            <span class="running-session-age">{age}</span>
        {/if}
        {#if rowId !== null}
            
            <span
                class="running-session-id"
                >#{rowId}</span
            >
        {/if}
    </div>
</div>
