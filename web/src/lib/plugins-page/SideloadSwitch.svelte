
<script lang="ts">
    import Check from '../../opscenter/ui/Check.svelte';
    import FacetSelect from '../../opscenter/ui/FacetSelect.svelte';
    import Button from '../base/Button.svelte';
    import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
    import { openModal } from '../modal';
    import type { Translate } from '../sessions/types';
    import SideloadConfirm from './SideloadConfirm.svelte';
    import SideloadLoadForm from './SideloadLoadForm.svelte';
    import { createSideloadStore, type SideloadStore } from './sideload-store.svelte';
    import { DURATION_HOURS, UNTIL_OFF, durationValue, hoursOf, untilWhen } from './sideload-switch';
    import './plugin-pane.css';

    interface Props {
        t: Translate;
        store?: SideloadStore;
        showStrip?: boolean;
    }

    const { t, store = createSideloadStore(), showStrip = true }: Props = $props();

    let busy = $state(false);
    let failed = $state(false);
    let picked = $state<string | null>(null);
    let opened = $state<'folder' | 'git' | null>(null);
    let folderButton = $state<HTMLElement | null>(null);
    let gitButton = $state<HTMLElement | null>(null);

    $effect(() => {
        void store.refresh();
    });

    const status = $derived(store.status);
    const duration = $derived(picked ?? durationValue(status?.hours));
    const options = $derived([
        ...DURATION_HOURS.map((h) => ({ value: String(h), label: t(`plugins.page.sideload.duration.${h}`) })),
        { value: UNTIL_OFF, label: t('plugins.page.sideload.duration.off') },
    ]);
    const until = $derived(untilWhen(status, t));

    async function toggle(next: boolean): Promise<void> {
        if (busy) return;
        if (next && !status?.enabled) {
            busy = true;
            const yes = await openModal(SideloadConfirm, { t });
            busy = false;
            if (yes !== true) return;
        }
        await flip(next);
    }

    async function flip(next: boolean): Promise<void> {
        if (busy) return;
        busy = true;
        failed = false;
        try {
            await store.setSwitch(next, next ? hoursOf(duration) : undefined);
            picked = null;
            if (!next) opened = null;
        } catch {
            failed = true;
        } finally {
            busy = false;
        }
    }

    function pick(value: string): void {
        picked = value;
        if (status?.enabled) void flip(true);
    }
</script>

{#if status || store.failed || failed}
<div data-sideload-switch style="display: contents">
    {#if status}
        <Check
            role="switch"
            label={t('plugins.page.sideload.label')}
            checked={status.enabled}
            disabled={busy}
            data-sideload-toggle="1"
            onToggle={(next) => void toggle(next)}
        />
        <FacetSelect id="sideload-duration" label={t('plugins.page.sideload.duration.label')} value={duration} {options} onChange={pick} />
        {#if until}
            <span class="plp-note" data-sideload-count>{t('plugins.page.sideload.count', { count: status.items.length })}</span>
        {/if}
        <Button size="sm" disabled={!status.enabled} bind:element={folderButton} data-sideload-open="folder" onclick={() => (opened = 'folder')}>
            {t('plugins.page.sideload.load_folder')}
        </Button>
        <Button size="sm" disabled={!status.enabled} bind:element={gitButton} data-sideload-open="git" onclick={() => (opened = 'git')}>
            {t('plugins.page.sideload.load_git')}
        </Button>
        {#if until && showStrip}
            
            <p class="plp-warn plp-danger sideload-strip" role="status" data-sideload-strip>
                {t('plugins.page.sideload.warning.strip')} <span data-sideload-until>{until}</span>
            </p>
        {/if}
        {#if opened}
            <AnchoredPopup label={t(opened === 'folder' ? 'plugins.page.sideload.load_folder' : 'plugins.page.sideload.load_git')}
                anchor={opened === 'folder' ? folderButton : gitButton} onClose={() => (opened = null)}>
                <SideloadLoadForm mode={opened} {t} onFolder={(path, name) => store.loadFolder(path, name)}
                    onGit={(request) => store.loadGit(request)} onDone={() => (opened = null)} />
            </AnchoredPopup>
        {/if}
    {/if}
    {#if failed || store.failed}<span class="plp-note" role="alert" data-sideload-failed>{t('plugins.page.sideload.failed')}</span>{/if}
</div>
{/if}

<style>
    @layer components {
        .sideload-strip {
            flex: 1 0 100%;
            margin: 0;
            padding: 0;
            border-left: 0;
            background: none;
            min-width: 0;
            font-size: var(--oc-fs-label, 11px);
            overflow-wrap: anywhere;
        }
    }
</style>
