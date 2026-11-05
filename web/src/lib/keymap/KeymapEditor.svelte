<!-- at the same time -->
<script lang="ts">
    import { onMount } from 'svelte';
    import Button from '../base/Button.svelte';
    import Keycap from '../base/Keycap.svelte';
    import Segmented from '../base/Segmented.svelte';
    import State from '../base/State.svelte';
    import Tag from '../base/Tag.svelte';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
    import { t } from '../i18n/index.svelte';
    import { caps, chordFromEvent } from '../../../../client/js/keymap/chord.js';
    import { chordsOf } from '../../../../client/js/keymap/effective.js';
    import { canSave, judge, MIDDLE } from './keymap-overrides';
    import { keymapStore } from './keymap-store.svelte';
    import { ALL_ACTIONS, scopeTagKey, type KeyboardFamily, type KeymapAction } from './keymap-view';

    interface Props {
        action: KeymapAction;
        family: KeyboardFamily;
        close: (value: 'saved' | 'reset' | null) => void;
    }

    const { action, family, close }: Props = $props();

    const isGesture = action.mouse.includes(MIDDLE) && action.keys.mac.length + action.keys.other.length === 0;
    let candidate = $state<string | null>(null);
    let failure = $state<string | null>(null);
    let busy = $state(false);
    let gestureOn = $state(((keymapStore.overrides.mouse ?? {})[action.id] ?? action.mouse).includes(MIDDLE));

    const current = $derived(chordsOf(action, family, keymapStore.overrides) as string[]);
    const changed = $derived(isGesture ? (keymapStore.overrides.mouse ?? {})[action.id] !== undefined : (keymapStore.overrides[family] ?? {})[action.id] !== undefined);
    const verdict = $derived(candidate ? judge(action, candidate, family, ALL_ACTIONS, keymapStore.overrides) : null);
    const saveable = $derived(isGesture ? true : candidate !== null && verdict !== null && canSave(verdict));

    function onKey(event: KeyboardEvent): void {
        if (isGesture || event.key === 'Tab') return;
        if (event.key === 'Escape' && !event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey) return;
        event.preventDefault();
        event.stopPropagation();
        const chord = chordFromEvent(event);
        if (chord !== null) candidate = chord;
    }

    onMount(() => {
        window.addEventListener('keydown', onKey, true);
        return () => window.removeEventListener('keydown', onKey, true);
    });

    async function commit(run: () => Promise<string | null>, outcome: 'saved' | 'reset'): Promise<void> {
        busy = true;
        failure = await run();
        busy = false;
        if (failure === null) close(outcome);
    }

    function save(): void {
        if (isGesture) void commit(() => keymapStore.set('mouse', action.id, gestureOn ? [MIDDLE] : []), 'saved');
        else if (candidate && saveable) void commit(() => keymapStore.set(family, action.id, [candidate as string]), 'saved');
    }

    const unbind = (): void => void commit(() => keymapStore.set(family, action.id, []), 'saved');

    const reset = (): void => void commit(() => keymapStore.reset(isGesture ? 'mouse' : family, action.id), 'reset');

</script>

<ModalShell title={t('keymap.editor.title')} overlayClass="text-prompt-modal keymap-editor" onCancel={() => close(null)} data-keymap-editor>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">&raquo; {t('keymap.editor.title')}</span>
        </div>
    {/snippet}

    <div class="keymap-editor__body">
        <p class="keymap-editor__for">{t(action.labelKey)} <Tag>{t(scopeTagKey(action.scope))}</Tag></p>

        <p class="keymap-editor__line">
            {t('keymap.editor.current')}
            {#each current as chord (chord)}<Keycap caps={caps(chord)} />{:else}<Tag>{t('keymap.none')}</Tag>{/each}
        </p>

        {#if isGesture}
            <Segmented
                label={t('keymap.editor.mouse')}
                bind:value={() => (gestureOn ? 'on' : 'off'), (v) => (gestureOn = v === 'on')}
                options={[{ value: 'on', label: t('keymap.editor.mouse.on') }, { value: 'off', label: t('keymap.editor.mouse.off') }]}
            />
        {:else}
            <div data-keymap-capture>
                <State inline kind="empty" title={candidate ? t('keymap.editor.pressed') : t('keymap.editor.press')}>
                    {#snippet children()}{#if candidate}<Keycap caps={caps(candidate)} hit />{/if}{/snippet}
                </State>
            </div>
            {#if verdict?.refused}
                <div data-keymap-refused><State inline kind="error" title={t(`keymap.refuse.${verdict.refused}`)} /></div>
            {/if}
            {#each verdict?.clashes ?? [] as other (other.id)}
                <div data-keymap-clash><State inline kind="error" title={t('keymap.editor.clash', { name: t(other.labelKey) })} /></div>
            {/each}
            {#each verdict?.overlaps ?? [] as other (other.id)}
                <div data-keymap-overlap><State inline kind="warn" title={t('keymap.editor.overlap', { name: t(other.labelKey) })} /></div>
            {/each}
        {/if}

        <p class="keymap-editor__line">{t('keymap.editor.saved_now')}</p>
        {#if failure}<div data-keymap-failed><State inline kind="error" title={t('keymap.editor.save_failed')} hint={failure} /></div>{/if}
    </div>

    {#snippet footer()}
        <Button onclick={() => close(null)}>{t('keymap.editor.cancel')}</Button>
        {#if !isGesture}<Button disabled={busy} onclick={unbind}>{t('keymap.editor.clear')}</Button>{/if}
        {#if changed}<Button disabled={busy} data-keymap-reset onclick={reset}>{t('keymap.editor.reset')}</Button>{/if}
        <Button variant="confirm" disabled={busy || !saveable} data-keymap-save onclick={save}>{t('keymap.editor.save')}</Button>
    {/snippet}
</ModalShell>

<style>
    @layer components {
        .keymap-editor__body {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
        }

        .keymap-editor__for,
        .keymap-editor__line {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--oc-space-2);
            margin: 0;
        }
    }
</style>
