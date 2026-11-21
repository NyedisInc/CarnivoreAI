
<script lang="ts">
    import { Button, Select } from '../base';
    import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
    import { authFetch } from '../../opscenter/api/auth.svelte';
    import { t } from '../i18n/index.svelte';
    import { playSound, playable } from '../notifications/sound-player';

    let { sessionName }: { sessionName?: string | null } = $props();

    interface Doc { sounds: string[]; types: Record<string, { override: string | null; global: string }> }

    const GLOBAL = '';
    let open = $state(false);
    let anchorEl: HTMLElement | null = $state(null);
    let popoverEl: HTMLElement | null = $state(null);
    let doc = $state<Doc | null>(null);

    const url = (name: string): string => `/notifications/session-sounds?name=${encodeURIComponent(name)}`;

    async function load(): Promise<void> {
        if (!sessionName) return;
        try { doc = await authFetch<Doc>(url(sessionName)); } catch { doc = null; }
    }

    async function choose(typeId: string, value: string): Promise<void> {
        if (!sessionName) return;
        try {
            doc = await authFetch<Doc>('/notifications/session-sounds', {
                method: 'PUT', body: JSON.stringify({ name: sessionName, type_id: typeId, sound: value === GLOBAL ? null : value }),
            });
            playSound(value === GLOBAL ? doc.types[typeId]?.global ?? '' : value);
        } catch {  }
    }

    function position(): void {
        const anchor = (globalThis as { AnchorPopover?: { place(el: HTMLElement, at: HTMLElement): unknown } }).AnchorPopover;
        if (anchor && popoverEl && anchorEl) anchor.place(popoverEl, anchorEl);
    }

    function close(): void {
        if (!open) return;
        open = false;
        anchorEl?.focus();
    }

    export function toggleAt(anchor: HTMLElement): void {
        anchorEl = anchor;
        if (open) { close(); return; }
        void load();
        open = true;
    }
</script>

{#if open}
    <AnchoredPopup bind:element={popoverEl} class="tsnd-pop" topLayer label={t('terminal.strip.sound')} anchor={anchorEl}
        placement="manual" onPlace={position} initialFocus="none" escape="document" outside="capture" onClose={close}>
        <div class="tsnd" data-tsnd>
            <div class="tsnd__title">{t('terminal.sound.title')}</div>
            {#if doc}
                {#each Object.entries(doc.types) as [typeId, row] (typeId)}
                    <div class="tsnd__row" data-tsnd-type={typeId}>
                        <span class="tsnd__lab">{t(`notify.type.${typeId}.label`)}</span>
                        <Select size="sm" aria-label={t(`notify.type.${typeId}.label`)} value={row.override ?? GLOBAL}
                            options={[{ value: GLOBAL, label: t('terminal.sound.global') }, ...doc.sounds.map((s) => ({ value: s, label: t(`notify.inspector.sound.${s}`) }))]}
                            onchange={(e) => void choose(typeId, (e.currentTarget as HTMLSelectElement).value)} />
                        <Button size="sm" data-tsnd-play disabled={!playable(row.override ?? row.global)}
                            onclick={() => playSound(row.override ?? row.global)}>{t('notify.inspector.play')}</Button>
                    </div>
                {/each}
            {/if}
        </div>
    </AnchoredPopup>
{/if}

<style>
  @layer components {
        :global(.tsnd-pop) {
            position: fixed;
            inset: auto;
            margin: 0;
            left: 0;
            top: 0;
            z-index: var(--oc-z-sheet);
            width: 340px;
            max-width: calc(100vw - 16px);
            border-radius: var(--oc-radius-sm);
        }
        .tsnd { display: grid; gap: var(--oc-space-2); padding: var(--oc-space-2) var(--oc-space-3); font-family: var(--font-mono); }
        .tsnd__title {
            height: 22px; display: flex; align-items: center; color: var(--oc-orange);
            font-size: var(--oc-fs-label); letter-spacing: var(--oc-tracking-label); text-transform: uppercase; box-shadow: 0 1px 0 var(--oc-line-rule);
        }
        .tsnd__row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: var(--oc-space-2); }
        .tsnd__lab { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--oc-text-secondary); font-size: var(--oc-fs-hint); }
  }
</style>
