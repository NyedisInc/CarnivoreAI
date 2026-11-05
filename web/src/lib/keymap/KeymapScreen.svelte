
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Keycap from '../base/Keycap.svelte';
    import Segmented from '../base/Segmented.svelte';
    import State from '../base/State.svelte';
    import Tag from '../base/Tag.svelte';
    import Toolbar from '../base/Toolbar.svelte';
    import Tree, { type TreeNode } from '../base/Tree.svelte';
    import ConfirmPopup from '../dialog-frame/ConfirmPopup.svelte';
    import { pageRowMenu } from '../item-menu/page-row';
    import { openModal } from '../modal';
    import { caps, chordFromEvent } from '../../../../client/js/keymap/chord.js';
    import { keyboardFamily } from '../../../../client/js/keymap/policy.js';
    import type { Translate } from '../sessions/types';
    import KeymapEditor from './KeymapEditor.svelte';
    import { isEmpty } from './keymap-overrides';
    import { keymapStore } from './keymap-store.svelte';
    import {
        clashingIds, gestureLabelKey, keycapRows, scopeTagKey, viewTree, type KeyboardFamily, type KeymapAction, type KeymapLeaf,
    } from './keymap-view';

    interface Props {
        query: string;
        t: Translate;
    }

    const { query, t }: Props = $props();

    keymapStore.start();

    let family = $state<KeyboardFamily>(keyboardFamily(typeof navigator === 'undefined' ? '' : navigator.platform));
    let listening = $state(false);
    let pressed = $state<string | null>(null);
    let open = $state<Record<string, boolean>>({});
    let resetButton = $state<HTMLElement | null>(null);
    let asking = $state(false);

    const view = $derived(viewTree({ text: query, pressed, family, t: (key) => t(key), overrides: keymapStore.overrides }));
    const clashes = $derived(clashingIds(family, keymapStore.overrides));

    function onKey(event: KeyboardEvent): void {
        if (event.key === 'Tab') return;
        event.preventDefault();
        event.stopPropagation();
        if (event.key === 'Escape' && !event.ctrlKey && !event.altKey && !event.metaKey && !event.shiftKey) {
            stop();
            return;
        }
        const chord = chordFromEvent(event);
        if (chord !== null) pressed = chord;
    }

    function stop(): void {
        listening = false;
        pressed = null;
    }

    function toggle(): void {
        if (listening) stop();
        else listening = true;
    }

    $effect(() => {
        if (!listening) return;
        window.addEventListener('keydown', onKey, true);
        return () => window.removeEventListener('keydown', onKey, true);
    });

    const editable = (action: KeymapAction): boolean => action.rebindable;

    const isChanged = (action: KeymapAction): boolean =>
        (keymapStore.overrides[family] ?? {})[action.id] !== undefined || (keymapStore.overrides.mouse ?? {})[action.id] !== undefined;

    function change(action: KeymapAction): void {
        if (editable(action)) void openModal(KeymapEditor, { action, family });
    }

    function rowMenu(action: KeymapAction): ReturnType<Parameters<typeof pageRowMenu>[0]> {
        if (!editable(action)) return null;
        const nodes = [{ id: 'change-shortcut', label: t('keymap.change.menu'), run: () => change(action) }];
        if (isChanged(action)) nodes.push({ id: 'reset-default', label: t('keymap.reset_one'), run: () => void keymapStore.reset(action.mouse.length > 0 && action.keys.mac.length + action.keys.other.length === 0 ? 'mouse' : family, action.id) });
        return { type: 'pagerow', ctx: { label: t(action.labelKey), nodes } };
    }

    const leafOf = (node: TreeNode): KeymapLeaf => node.data as KeymapLeaf;

    function resetAll(): void {
        asking = false;
        void keymapStore.resetAll();
    }
</script>

<div class="keymap" data-keymap>
    <div data-keymap-note><State inline kind="empty" title={t('keymap.note')} /></div>

    <Toolbar wrap label={t('keymap.find.name.label')}>
        {#snippet extras()}
            <Button size="sm" aria-pressed={listening} data-keymap-press onclick={toggle}>
                {listening ? t('keymap.find.press.stop') : t('keymap.find.press')}
            </Button>
            <Button size="sm" variant="danger" disabled={isEmpty(keymapStore.overrides)} bind:element={resetButton} data-keymap-reset-all onclick={() => (asking = true)}>
                {t('keymap.reset_all')}
            </Button>
        {/snippet}
        {#snippet end()}
            <Segmented
                label={t('keymap.family.label')}
                bind:value={family as string}
                options={[{ value: 'mac', label: t('keymap.family.mac') }, { value: 'other', label: t('keymap.family.other') }]}
            />
        {/snippet}
    </Toolbar>

    {#if asking}
        <ConfirmPopup label={t('keymap.reset_all')} message={t('keymap.reset_all.confirm')} anchor={resetButton} cancelLabel={t('keymap.reset_all.no')}
            confirmLabel={t('keymap.reset_all.yes')} onConfirm={resetAll} onCancel={() => (asking = false)} data-keymap-reset-confirm />
    {/if}

    {#if listening}
        <div data-keymap-hint>
            {#if pressed}
                <State inline kind="empty" title={t('keymap.find.press.pressed')} hint={view.total === 0 ? t('keymap.find.press.none') : undefined}>
                    {#snippet children()}<Keycap caps={caps(pressed ?? '')} hit />{/snippet}
                </State>
            {:else}
                <State inline kind="empty" title={t('keymap.find.press.hint')} />
            {/if}
        </div>
    {/if}

    {#if view.total === 0 && !listening}
        <State kind="empty" title={t('keymap.empty')} />
    {/if}

    <Tree nodes={view.nodes} label={t('keymap.tree.label')} bind:open forceOpen={view.searching} onActivate={(node) => change(leafOf(node).action)}>
        {#snippet leaf(node)}
            {@const { action, itemId } = leafOf(node)}
            <span class="keymap__leaf" data-action={action.id} data-item={itemId} 
                ondblclick={() => change(action)} {...pageRowMenu(() => rowMenu(action))}>
                <span class="keymap__label">{node.label}</span>
                <span class="keymap__meta">
                    {#if clashes.has(action.id)}<Tag tone="danger">{t('keymap.clash')}</Tag>{/if}
                    {#if !itemId && action.category !== 'standard'}<Tag>{t(scopeTagKey(action.scope))}</Tag>{/if}
                    {#if isChanged(action)}
                        <Tag tone="accent">{t('keymap.changed')}</Tag>
                    {/if}
                    {#each keycapRows(action, family, keymapStore.overrides) as caps, i (i)}<Keycap {caps} hit={pressed !== null} />{/each}
                    {#each action.mouse as gesture (gesture)}<Tag tone="info">{t(gestureLabelKey(gesture))}</Tag>{/each}
                    {#if keycapRows(action, family, keymapStore.overrides).length === 0 && action.mouse.length === 0}<Tag>{t('keymap.none')}</Tag>{/if}
                </span>
            </span>
        {/snippet}
        {#snippet actions(node)}
            {@const { action } = leafOf(node)}
            {#if editable(action)}
                <Button size="sm" data-keymap-change data-action-for={action.id} title={t('keymap.change.title', { name: node.label })} onclick={() => change(action)}>{t('keymap.change')}</Button>
            {/if}
        {/snippet}
    </Tree>
</div>

<style>
    @layer components {
        .keymap__leaf {
            display: flex;
            flex: 1 1 auto;
            align-items: center;
            gap: var(--oc-space-2);
            min-width: 0;
        }

        .keymap__label {
            flex: 1 1 auto;
            min-width: 0;
        }

        .keymap__meta {
            display: inline-flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: flex-end;
            gap: var(--oc-space-2);
        }
    }
</style>
