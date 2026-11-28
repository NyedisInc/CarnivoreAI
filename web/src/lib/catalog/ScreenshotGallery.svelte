
<script lang="ts">
    import { SKILL_KEYS } from '../../../../client/js/labels/skill.js';
    import Tag from '../base/Tag.svelte';
    import { openModal } from '../modal';
    import type { Translate } from '../sessions/types';
    import { catalogApiImageUrl, catalogMediaUrl } from './card-media';
    import { isReadonly } from './readonly';
    import ScreenshotLightbox from './ScreenshotLightbox.svelte';

    export interface ScreenshotItem {
        readonly sha?: string | null;
        readonly url?: string | null;
        readonly w?: number | null;
        readonly h?: number | null;
        readonly source?: 'author' | 'captured' | null;
        readonly surface?: string | null;
        readonly caption?: string | null;
    }

    interface Props {
        screenshots: readonly ScreenshotItem[];
        itemName?: string | null;
        t: Translate;
    }

    const { screenshots, itemName = null, t }: Props = $props();
    const readonly = isReadonly();

    let resolved = $state<Record<number, string>>({});

    $effect(() => {
        const list = screenshots;
        resolved = {};
        let cancelled = false;
        list.forEach((shot, idx) => {
            if (shot.sha) {
                if (readonly) {
                    resolved = { ...resolved, [idx]: `v1/media/${encodeURIComponent(shot.sha)}.webp` };
                } else {
                    void catalogMediaUrl(shot.sha).then((blobUrl) => {
                        if (!cancelled && blobUrl) resolved = { ...resolved, [idx]: blobUrl };
                    });
                }
            } else if (shot.url) {
                void catalogApiImageUrl(shot.url).then((blobUrl) => {
                    if (!cancelled && blobUrl) resolved = { ...resolved, [idx]: blobUrl };
                });
            }
        });
        return () => {
            cancelled = true;
        };
    });

    function openAt(idx: number): void {
        if (!resolved[idx]) return;
        void openModal(ScreenshotLightbox, {
            screenshots,
            resolved,
            initialIndex: idx,
            itemName,
            t,
        });
    }
</script>

{#if screenshots.length > 0}
    <section class="ss-gal" aria-label={t(SKILL_KEYS.screenshotsHeading)} data-screenshot-gallery>
        <p class="ss-gal__heading">{t(SKILL_KEYS.screenshotsHeading)}</p>
        <div class="ss-gal__grid">
            {#each screenshots as shot, idx}
                <button
                    type="button"
                    class="ss-gal__thumb"
                    data-btn="row"
                    data-screenshot-thumb={idx}
                    disabled={!resolved[idx]}
                    aria-label={shot.caption || t(SKILL_KEYS.screenshotOpenAria, { index: String(idx + 1) })}
                    onclick={() => openAt(idx)}
                >
                    <span class="ss-gal__frame">
                        {#if resolved[idx]}
                            <img
                                class="ss-gal__img"
                                src={resolved[idx]}
                                alt={shot.caption || itemName || t(SKILL_KEYS.screenshotsHeading)}
                                loading="lazy"
                            />
                        {/if}
                    </span>
                    {#if shot.caption || shot.source === 'captured'}
                        <span class="ss-gal__cap">
                            {#if shot.caption}
                                <span class="ss-gal__cap-text">{shot.caption}</span>
                            {/if}
                            {#if shot.source === 'captured'}
                                <Tag tone="info">{t(SKILL_KEYS.screenshotCapturedBadge)}</Tag>
                            {/if}
                        </span>
                    {/if}
                </button>
            {/each}
        </div>
    </section>
{/if}

<style>
  @layer components {
    .ss-gal {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
    }

    .ss-gal__heading {
        margin: 0;
        color: var(--oc-text-muted);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro);
        letter-spacing: var(--oc-tracking-label);
        text-transform: uppercase;
    }

    .ss-gal__grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
        gap: var(--oc-space-2);
    }

    .ss-gal__thumb {
        display: flex;
        flex-direction: column;
        align-items: stretch;
        gap: var(--oc-space-1);
        width: 100%;
        min-width: 0;
        overflow: hidden;
        padding: var(--oc-space-1);
        border: var(--oc-border) solid var(--oc-line-panel);
        border-radius: var(--oc-radius-control);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        cursor: pointer;
        text-align: left;
        transition: border-color var(--oc-motion-fast) ease;
    }

    .ss-gal__thumb:hover:not(:disabled) {
        border-color: var(--oc-orange);
    }

    .ss-gal__thumb:disabled {
        cursor: default;
        opacity: 0.6;
    }

    .ss-gal__frame {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        aspect-ratio: 16 / 10;
        overflow: hidden;
        border-radius: var(--oc-radius-control);
        background: var(--oc-ground-page);
    }

    .ss-gal__img {
        width: 100%;
        height: 100%;
        object-fit: contain;
        display: block;
    }

    .ss-gal__cap {
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: var(--oc-space-1);
        width: 100%;
        min-width: 0;
    }

    .ss-gal__cap-text {
        display: block;
        width: 100%;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: var(--oc-fs-micro);
        color: var(--oc-text-secondary);
    }
  }
</style>
