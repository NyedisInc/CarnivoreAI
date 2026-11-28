
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import IconButton from '../base/IconButton.svelte';
    import Tag from '../base/Tag.svelte';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
    import type { Closable } from '../modal';
    import type { Translate } from '../sessions/types';
    import type { ScreenshotItem } from './ScreenshotGallery.svelte';

    interface Props extends Closable<null> {
        screenshots: readonly ScreenshotItem[];
        resolved: Readonly<Record<number, string>>;
        initialIndex: number;
        itemName?: string | null;
        t: Translate;
    }

    const { screenshots, resolved, initialIndex, itemName = null, t, close }: Props = $props();

    let activeIdx = $state(0);

    $effect(() => {
        activeIdx = Math.max(0, Math.min(initialIndex, Math.max(0, screenshots.length - 1)));
    });

    const activeShot = $derived(screenshots[activeIdx] ?? null);
    const activeUrl = $derived(resolved[activeIdx] ?? null);
    const canStep = $derived(screenshots.length > 1);

    function step(delta: number): void {
        if (screenshots.length < 2) return;
        activeIdx = (activeIdx + delta + screenshots.length) % screenshots.length;
    }

    function onKeydown(event: KeyboardEvent): void {
        if (event.key === 'ArrowLeft') {
            event.preventDefault();
            step(-1);
        } else if (event.key === 'ArrowRight') {
            event.preventDefault();
            step(1);
        }
    }
</script>

<svelte:window onkeydown={onKeydown} />

{#if activeShot && activeUrl}
    <ModalShell
        title={activeShot.caption || itemName || t(SKILL_KEYS.screenshotsHeading)}
        look="titlerow"
        width="min(960px, 94vw)"
        onCancel={() => close(null)}
        data-screenshot-lightbox
    >
        <div class="ss-gal__stage">
            <img
                class="ss-gal__full"
                src={activeUrl}
                alt={activeShot.caption || itemName || t(SKILL_KEYS.screenshotsHeading)}
            />
        </div>
        {#snippet footer()}
            <div class="ss-gal__bar">
                <span class="ss-gal__meta">
                    {activeIdx + 1} / {screenshots.length}
                    {#if activeShot.w && activeShot.h}
                        &middot; {activeShot.w}&times;{activeShot.h}
                    {/if}
                    {#if activeShot.source === 'captured'}
                        <Tag tone="info">{t(SKILL_KEYS.screenshotCapturedBadge)}</Tag>
                    {/if}
                </span>
                {#if canStep}
                    <div class="ss-gal__nav">
                        <IconButton
                            icon="chevron-left"
                            label={t(SKILL_KEYS.screenshotPrev)}
                            data-screenshot-prev
                            onclick={() => step(-1)}
                        />
                        <IconButton
                            icon="chevron-right"
                            label={t(SKILL_KEYS.screenshotNext)}
                            data-screenshot-next
                            onclick={() => step(1)}
                        />
                    </div>
                {/if}
            </div>
        {/snippet}
    </ModalShell>
{/if}

<style>
  @layer components {
    .ss-gal__stage {
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--oc-ground-page);
        border: var(--oc-border) solid var(--oc-line-faint);
        border-radius: var(--oc-radius-control);
        overflow: hidden;
    }

    .ss-gal__full {
        max-width: 100%;
        max-height: 70vh;
        width: auto;
        height: auto;
        display: block;
        object-fit: contain;
    }

    .ss-gal__bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--oc-space-2);
        width: 100%;
    }

    .ss-gal__meta {
        display: flex;
        align-items: center;
        gap: var(--oc-space-1-5);
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-label);
    }

    .ss-gal__nav {
        display: flex;
        align-items: center;
        gap: var(--oc-space-1);
    }
  }
</style>
