
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { Translate } from '../sessions/types';
    import { harnessesOf } from './installed-rows';
    import type { InstalledItem } from './types';

    interface Props {
        rows: readonly InstalledItem[];
        activeId?: string | null;
        onPick?: ((installId: string) => void) | null;
        t: Translate;
    }

    const { rows, activeId = null, onPick = null, t }: Props = $props();

    function folder(row: InstalledItem): string {
        const path = row.project_path ?? '';
        return path.split('/').filter(Boolean).pop() ?? path;
    }
</script>

<section class="cat-where" aria-label={t(BROWSE_KEYS.whereHeading)}>
    <span class="cat-where__heading">{t(BROWSE_KEYS.whereHeading)}</span>
    {#if rows.length}
        <ul class="cat-where__grid">
            {#each rows as row (row.install_id ?? `${row.scope}:${row.project_path}`)}
                {@const harnesses = harnessesOf(row)}
                <li class="cat-where__row" class:cat-where__row--on={!!row.install_id && row.install_id === activeId}>
                    <button
                        type="button"
                        class="cat-where__scope"
                        disabled={!onPick || !row.install_id}
                        onclick={() => row.install_id && onPick?.(row.install_id)}
                    >
                        {row.scope === 'project'
                            ? t(BROWSE_KEYS.whereProject, { folder: folder(row) })
                            : t(BROWSE_KEYS.whereGlobal)}
                    </button>
                    <span class="cat-where__harnesses">
                        {harnesses.length
                            ? t(BROWSE_KEYS.whereHarnesses, { harnesses: harnesses.join(', ') })
                            : t(BROWSE_KEYS.whereNoHarness)}
                    </span>
                </li>
            {/each}
        </ul>
    {:else}
        <p class="cat-where__note">{t(BROWSE_KEYS.whereNone)}</p>
    {/if}
</section>

<style>
    .cat-where {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .cat-where__heading {
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-where__grid {
        display: flex;
        flex-direction: column;
        margin: 0;
        padding: 0;
        list-style: none;
        border-top: 1px solid var(--cat-line);
    }

    .cat-where__row {
        display: flex;
        align-items: baseline;
        gap: 10px;
        padding: 4px 0;
        border-bottom: 1px solid var(--cat-line);
        font-family: var(--cat-mono);
        font-size: 11px;
    }

    .cat-where__scope {
        padding: 0;
        border: none;
        background: transparent;
        color: var(--cat-text);
        font: inherit;
        cursor: pointer;
    }

    .cat-where__scope:disabled {
        cursor: default;
    }

    .cat-where__row--on .cat-where__scope {
        color: var(--cat-action);
    }

    .cat-where__harnesses {
        color: var(--cat-muted);
    }

    .cat-where__note {
        margin: 0;
        color: var(--cat-muted);
        font-size: 12px;
    }
</style>
