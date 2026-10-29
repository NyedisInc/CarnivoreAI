
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import type { Translate } from '../sessions/types';
    import type { InstalledItem } from './types';

    interface Props {
        installed: InstalledItem;
        t: Translate;
    }

    const { installed, t }: Props = $props();

    const drift = $derived(installed.drift ?? null);
    const line = $derived(
        drift === null
            ? BROWSE_KEYS.driftUnknown
            : drift.state === 'clean'
              ? BROWSE_KEYS.driftClean
              : drift.state === 'drifted'
                ? BROWSE_KEYS.driftDrifted
                : drift.state === 'missing'
                  ? BROWSE_KEYS.driftMissing
                  : BROWSE_KEYS.driftUnknown,
    );
    const files = $derived(drift && drift.state === 'drifted' ? (drift.changed_files ?? null) : undefined);
</script>

<section class="cat-drift" aria-label={t(BROWSE_KEYS.driftHeading)} data-drift={drift?.state ?? 'unknown'}>
    <span class="cat-drift__heading">{t(BROWSE_KEYS.driftHeading)}</span>
    <p class="cat-drift__fact" class:cat-drift__fact--bad={drift?.state === 'drifted' || drift?.state === 'missing'}>
        {t(line)}
    </p>
    {#if files !== undefined}
        <p class="cat-drift__files">
            {files === null ? t(BROWSE_KEYS.driftFilesUnknown) : t(BROWSE_KEYS.driftFiles, { files: files.join(', ') })}
        </p>
    {/if}
    {#if installed.forked}
        <p class="cat-drift__files">{t(BROWSE_KEYS.driftFork)}</p>
    {/if}
</section>

<style>
    .cat-drift {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .cat-drift__heading {
        color: var(--cat-muted);
        font-family: var(--cat-mono);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .cat-drift__fact,
    .cat-drift__files {
        margin: 0;
        color: var(--cat-text);
        font-family: var(--cat-mono);
        font-size: 11px;
    }

    .cat-drift__fact--bad {
        color: var(--cat-failure);
    }

    .cat-drift__files {
        color: var(--cat-muted);
        overflow-wrap: anywhere;
    }
</style>
