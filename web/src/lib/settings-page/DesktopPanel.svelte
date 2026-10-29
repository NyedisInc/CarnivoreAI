
<script lang="ts">
    import { onDestroy } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import RadioGroup from '../base/RadioGroup.svelte';
    import State from '../base/State.svelte';
    import Switch from '../base/Switch.svelte';
    import './panel-kit/panel-kit.css';
    import { errorText } from './panel-kit/error-text';
    import { desktopBridge, hasDesktopCapability, type DesktopBridge, type DesktopLogin, type DesktopState, type NotificationState } from './desktop-bridge';
    import { DESKTOP_PREF_DEFAULTS, TERMINAL_APPS, livePrefs, type DesktopPrefField, type DesktopPrefValues, type DesktopPrefs } from './desktop-prefs';
    import { acceleratorOf } from './desktop-hotkey';
    import { bindKind, tlsKey } from './desktop-network';
    import { settingsDoc } from './settings-doc.svelte';

    interface Props {
        t?: Translate;
        bridge?: DesktopBridge | null;
        prefs?: DesktopPrefs;
        effectiveBind?: string | null;
    }
    const { t = reactiveT, bridge = desktopBridge(), prefs = livePrefs, effectiveBind }: Props = $props();

    const PERMISSION_STATES: readonly NotificationState[] = ['allowed', 'not_asked', 'denied', 'unknown'];

    // svelte-ignore state_referenced_locally
    const present = hasDesktopCapability('desktopState', bridge);
    let shell = $state<DesktopState | null>(null);
    let values = $state<DesktopPrefValues>({ ...DESKTOP_PREF_DEFAULTS });
    let customDraft = $state('');
    let redraw = $state(0);
    let busy = $state(false);
    let problem = $state('');

    const fields = Object.keys(DESKTOP_PREF_DEFAULTS) as DesktopPrefField[];
    const permission = $derived.by((): NotificationState => {
        const reported = shell?.notifications?.state;
        return reported && PERMISSION_STATES.includes(reported) ? reported : 'unknown';
    });
    const measuredBind = $derived(effectiveBind !== undefined ? effectiveBind : (settingsDoc.summary?.server_prefs?.effective_bind_host ?? null));
    const bind = $derived(bindKind(measuredBind));
    const bindText = $derived(bind === 'unknown' ? t('desktop.settings.unknown')
        : bind === 'specific' ? t('desktop.settings.bind.specific', { host: measuredBind!.trim() }) : t(`desktop.settings.bind.${bind}`));
    const hotkeyError = $derived(shell?.hotkey?.error ?? '');
    const customDirty = $derived(customDraft.trim() !== values.desktop_terminal_custom);

    function reread(): void {
        const next = { ...values } as Record<string, unknown>;
        for (const field of fields) next[field] = prefs.read(field);
        values = next as unknown as DesktopPrefValues;
        customDraft = values.desktop_terminal_custom;
    }

    async function loadState(): Promise<void> {
        try {
            shell = await bridge!.desktopState!();
        } catch (error) {
            problem = errorText(error);
        }
    }

    let stops: Array<() => void> = [];
    if (present) {
        reread();
        void loadState();
        stops = fields.map((field) => prefs.follow(field, () => reread()));
    }
    onDestroy(() => stops.forEach((stop) => stop()));

    async function save<K extends DesktopPrefField>(field: K, value: DesktopPrefValues[K] | null): Promise<boolean> {
        busy = true;
        problem = '';
        const why = await prefs.write(field, value);
        reread();
        if (field === 'desktop_hotkey' && why === null) await loadState();
        busy = false;
        if (why) problem = t('desktop.settings.error.save', { reason: why });
        return why === null;
    }

    async function setBanners(next: boolean): Promise<void> {
        const saved = await save('desktop_banners', next);
        if (!saved || !next || shell?.notifications?.state !== 'not_asked' || !hasDesktopCapability('requestNotifications', bridge)) return;
        try {
            shell = { ...shell!, notifications: await bridge!.requestNotifications!() };
        } catch (error) {
            problem = errorText(error);
        }
    }

    async function setLogin(which: 'engine' | 'window', next: boolean): Promise<void> {
        busy = true;
        problem = '';
        try {
            const login: DesktopLogin = await bridge!.setLoginItem!(which, next);
            shell = { ...shell!, login };
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }

    async function openSettings(): Promise<void> {
        try {
            await bridge!.openNotificationSettings!();
        } catch (error) {
            problem = errorText(error);
        }
    }

    async function openFocus(): Promise<void> {
        try {
            await bridge!.openFocusSettings!();
        } catch (error) {
            problem = errorText(error);
        }
    }

    function onHotkeyKey(event: KeyboardEvent): void {
        if (event.key === 'Tab') return;
        event.preventDefault();
        const accelerator = acceleratorOf(event);
        if (accelerator) void save('desktop_hotkey', accelerator);
    }
</script>

{#if present}
    <div class="tm" data-desktop="panel">
        {#if shell}
            <Switch label={t('desktop.settings.banners')} hint={t('desktop.settings.banners_hint')}
                bind:checked={() => values.desktop_banners, (next) => void setBanners(next)} disabled={busy} data-desktop="banners" />
            <p class="tm__sub" role="status" data-desktop="permission" data-state={permission}>
                {t('desktop.settings.permission')}: {t(`desktop.settings.permission.${permission}`)}
            </p>
            {#if values.desktop_banners && permission === 'not_asked'}
                <p class="tm__sub" role="status" data-desktop="banners-not-posting">{t('desktop.settings.banners_not_posting')}</p>
            {/if}
            {#if values.desktop_banners && permission === 'unknown' && shell?.notifications?.waiting === true}
                <p class="tm__sub" role="status" data-desktop="banners-waiting">{t('desktop.settings.banners_waiting')}</p>
            {/if}
            {#if (permission === 'denied' || permission === 'unknown') && hasDesktopCapability('openNotificationSettings', bridge)}
                <div class="tm__actions">
                    <Button size="sm" data-desktop="open-settings" onclick={() => void openSettings()}>
                        {t('desktop.settings.permission_open_settings')}
                    </Button>
                </div>
            {/if}
            <p class="tm__sub" data-desktop="banners-partial">{t('desktop.settings.banners_partial')}</p>
            <Switch label={t('desktop.settings.hide_command')} hint={t('desktop.settings.hide_command_hint')}
                bind:checked={() => values.desktop_banner_hide_command, (next) => void save('desktop_banner_hide_command', next)} disabled={busy} data-desktop="hide-command" />

            <Switch label={t('desktop.settings.asks_only')} hint={t('desktop.settings.asks_only_hint')}
                bind:checked={() => values.desktop_notify_asks_only, (next) => void save('desktop_notify_asks_only', next)} disabled={busy} data-desktop="asks-only" />
            <p class="tm__sub" data-desktop="focus-note">{t('desktop.settings.focus_note')}</p>
            {#if hasDesktopCapability('openFocusSettings', bridge)}
                <div class="tm__actions">
                    <Button size="sm" data-desktop="open-focus" onclick={() => void openFocus()}>
                        {t('desktop.settings.focus_open')}
                    </Button>
                </div>
            {/if}

            <div class="tm__field">
                <p class="tm__figs">{t('desktop.settings.hotkey')}</p>
                <p class="tm__sub">{t('desktop.settings.hotkey_hint')}</p>
                <Field readonly spellcheck={false} autocomplete="off" data-desktop="hotkey"
                    aria-label={t('desktop.settings.hotkey')} placeholder={t('desktop.settings.hotkey_record')}
                    value={values.desktop_hotkey || t('desktop.settings.hotkey_off')} onkeydown={onHotkeyKey} />
                <div class="tm__actions">
                    <Button size="sm" data-desktop="hotkey-clear" disabled={busy || values.desktop_hotkey === ''}
                        onclick={() => void save('desktop_hotkey', '')}>{t('desktop.settings.hotkey_clear')}</Button>
                    <Button size="sm" data-desktop="hotkey-reset" disabled={busy || values.desktop_hotkey === DESKTOP_PREF_DEFAULTS.desktop_hotkey}
                        onclick={() => void save('desktop_hotkey', null)}>{t('desktop.settings.hotkey_reset')}</Button>
                </div>
                {#if hotkeyError}
                    <State kind="error" inline data-desktop="hotkey-error"
                        title={t('desktop.settings.hotkey_failed', { accelerator: values.desktop_hotkey, reason: hotkeyError })} />
                {/if}
            </div>

            <Switch label={t('desktop.settings.option_meta')} hint={t('desktop.settings.option_meta_hint')}
                bind:checked={() => values.mac_option_is_meta, (next) => void save('mac_option_is_meta', next)} disabled={busy} data-desktop="option-meta" />
            <Switch label={t('desktop.settings.menu_bar_icon')} hint={t('desktop.settings.menu_bar_icon_hint')}
                bind:checked={() => values.desktop_menu_bar_icon, (next) => void save('desktop_menu_bar_icon', next)} disabled={busy} data-desktop="menu-bar-icon" />

            <Switch label={t('desktop.settings.login.engine')} hint={t('desktop.settings.login.engine_hint')}
                bind:checked={() => shell?.login?.engine === true, (next) => void setLogin('engine', next)} disabled={busy || !hasDesktopCapability('setLoginItem', bridge)} data-desktop="login-engine" />
            <Switch label={t('desktop.settings.login.window')} hint={t('desktop.settings.login.window_hint')}
                bind:checked={() => shell?.login?.window === true, (next) => void setLogin('window', next)} disabled={busy || !hasDesktopCapability('setLoginItem', bridge)} data-desktop="login-window" />

            <div class="tm__field">
                <p class="tm__figs">{t('desktop.settings.terminal')}</p>
                <p class="tm__sub">{t('desktop.settings.terminal_hint')}</p>
                <div data-desktop="terminal">
                    {#key redraw}<RadioGroup label={t('desktop.settings.terminal')} disabled={busy} orientation="horizontal"
                        bind:value={() => values.desktop_terminal_app, (app) => { if (!busy && values.desktop_terminal_app !== app) void save('desktop_terminal_app', app).then((saved) => { if (!saved) redraw += 1; }); }}
                        options={TERMINAL_APPS.map((app) => ({ value: app, label: t(`desktop.settings.terminal.${app}`) }))} />{/key}
                </div>
                {#if values.desktop_terminal_app === 'custom'}
                    <form class="tm__field" onsubmit={(event) => { event.preventDefault(); void save('desktop_terminal_custom', customDraft.trim() || null); }}>
                        <Field maxlength={500} spellcheck={false} autocomplete="off" autocapitalize="off" data-desktop="custom"
                            aria-label={t('desktop.settings.terminal_custom')} placeholder={t('desktop.settings.terminal_custom_placeholder')}
                            bind:value={customDraft} disabled={busy} />
                        <p class="tm__sub">{t('desktop.settings.terminal_custom_hint')}</p>
                        <div class="tm__actions">
                            <Button type="submit" variant="confirm" data-desktop="custom-save" disabled={busy || !customDirty}>
                                {t('desktop.settings.terminal_custom_save')}
                            </Button>
                        </div>
                    </form>
                {/if}
            </div>

            <div class="tm__field" data-desktop="network">
                <p class="tm__figs">{t('desktop.settings.network')}</p>
                <p class="tm__sub" data-desktop="bind" data-kind={bind}>{t('desktop.settings.bind')}: {bindText}</p>
                <p class="tm__sub" data-desktop="tls" data-level={shell.network?.tls ?? 'unknown'}>
                    {t('desktop.settings.tls')}: {t(tlsKey(shell.network?.tls, bind))}
                </p>
                <p class="tm__sub" data-desktop="network-hint">{t('desktop.settings.network_hint')}</p>
            </div>
        {:else if !problem}
            <p class="tm__sub">{t('desktop.settings.loading')}</p>
        {/if}
        {#if problem}<State kind="error" inline data-desktop="problem" title={problem} />{/if}
    </div>
{/if}
