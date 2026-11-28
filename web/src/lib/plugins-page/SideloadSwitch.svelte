
<script lang="ts">
    import Check from '../../opscenter/ui/Check.svelte';
    import FacetSelect from '../../opscenter/ui/FacetSelect.svelte';
    import Button from '../base/Button.svelte';
    import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
    import { openModal } from '../modal';
    import type { Translate } from '../sessions/types';
    import SideloadConfirm from './SideloadConfirm.svelte';
    import SideloadConsent from './SideloadConsent.svelte';
    import { createDropFlow, desktopBridge, folderOfPicked, pathOfDrop } from './drop-folder';
    import SideloadLoadForm from './SideloadLoadForm.svelte';
    import { createSideloadStore, type SideloadStore } from './sideload-store.svelte';
    import { DURATION_HOURS, UNTIL_OFF, durationValue, hoursOf, refusalText, untilWhen, type SideloadSheet } from './sideload-switch';
    import type { InstallConsent } from '../catalog/types';
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

    const flow = createDropFlow(store);
    let dropSheet = $state<SideloadSheet | null>(null);
    let dropNote = $state<string | null>(null);
    let dragging = $state(false);
    let picker = $state<HTMLInputElement | null>(null);

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

    async function loadPath(path: string): Promise<void> {
        dropNote = null;
        if (!status?.enabled) {
            dropNote = t('plugins.page.sideload.drop.needs_on');
            return;
        }
        await flow.drop(path);
        dropSheet = flow.sheet;
        if (flow.error) dropNote = refusalText(flow.error, t);
    }

    async function confirmDrop(consent: InstallConsent): Promise<void> {
        await flow.confirm(consent);
        if (flow.error) throw flow.error;
        dropSheet = null;
    }

    function cancelDrop(): void {
        flow.cancel();
        dropSheet = null;
    }

    function hasFiles(event: DragEvent): boolean {
        return Array.from(event.dataTransfer?.types ?? []).includes('Files');
    }

    function onDragOver(event: DragEvent): void {
        if (!hasFiles(event)) return;
        event.preventDefault();
        dragging = true;
    }

    function onDrop(event: DragEvent): void {
        dragging = false;
        if (!hasFiles(event) || !event.dataTransfer) return;
        event.preventDefault();
        const found = pathOfDrop(event.dataTransfer, desktopBridge());
        if ('path' in found) void loadPath(found.path);
        else dropNote = t(`plugins.page.sideload.drop.${found.problem}`);
    }

    function addFromFolder(): void {
        if (desktopBridge() && picker) picker.click();
        else opened = 'folder';
    }

    function onPicked(event: Event): void {
        const input = event.currentTarget as HTMLInputElement;
        const first = input.files?.[0];
        const bridge = desktopBridge();
        const full = first && bridge ? (bridge.droppedPaths([first])[0] ?? '') : '';
        const folder = first ? folderOfPicked(first, full) : null;
        input.value = '';
        if (folder) void loadPath(folder);
        else dropNote = t('plugins.page.sideload.drop.no_path');
    }

    function pick(value: string): void {
        picked = value;
        if (status?.enabled) void flip(true);
    }
</script>

<svelte:window ondragover={onDragOver} ondragleave={() => (dragging = false)} ondrop={onDrop} />

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
        <Button size="sm" disabled={!status.enabled} bind:element={folderButton} data-sideload-open="folder" onclick={addFromFolder}>
            {t('plugins.page.sideload.load_folder')}
        </Button>
        
        <input type="file" hidden webkitdirectory bind:this={picker} data-sideload-picker onchange={onPicked} />
        {#if dragging}<span class="plp-note" data-sideload-dropping>{t('plugins.page.sideload.drop.hint')}</span>{/if}
        {#if dropNote}<span class="plp-note" role="alert" data-sideload-drop-note>{dropNote}</span>{/if}
        <Button size="sm" disabled={!status.enabled} bind:element={gitButton} data-sideload-open="git" onclick={() => (opened = 'git')}>
            {t('plugins.page.sideload.load_git')}
        </Button>
        {#if until && showStrip}
            
            <p class="plp-warn plp-danger sideload-strip" role="status" data-sideload-strip>
                {t('plugins.page.sideload.warning.strip')} <span data-sideload-until>{until}</span>
            </p>
        {/if}
        {#if dropSheet}
            <AnchoredPopup label={t('plugins.page.sideload.load_folder')} anchor={folderButton} onClose={cancelDrop}>
                <SideloadConsent sheet={dropSheet} {t} onConfirm={confirmDrop} onCancel={cancelDrop} />
            </AnchoredPopup>
        {/if}
        {#if opened}
            <AnchoredPopup label={t(opened === 'folder' ? 'plugins.page.sideload.load_folder' : 'plugins.page.sideload.load_git')}
                anchor={opened === 'folder' ? folderButton : gitButton} onClose={() => (opened = null)}>
                <SideloadLoadForm mode={opened} {t} onFolder={(path, name, consent) => store.loadFolder(path, name, consent)}
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
