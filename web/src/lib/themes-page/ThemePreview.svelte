
<script lang="ts">
    import { previewStyle, type PreviewPalette } from './preview-palette';

    interface Props {
        palette: PreviewPalette;
        size?: 'card' | 'large';
        label?: string;
    }

    let { palette, size = 'card', label = '' }: Props = $props();

    /* failed to load */
    let artFailed = $state(false);

    const art = $derived(size === 'large' ? (palette.background ?? palette.artwork) : palette.artwork);
    $effect(() => {
        void art;
        artFailed = false;
    });

    const BAR_ROWS: [number, number][][] = [
        [[-1, 10], [4, 18], [2, 26]],
        [[10, 8], [7, 44]],
        [[3, 12], [7, 30]],
        [[1, 12], [7, 22], [9, 10]],
        [[6, 16], [5, 20], [7, 12]],
    ];

    const TEXT_ROWS: [number, string][][] = [
        [[-1, 'carnivore'], [4, '~/dev'], [-2, '$'], [2, 'claude']],
        [[2, 'ok'], [-2, 'build'], [8, '1.2s']],
        [[3, 'warn'], [-2, 'lint'], [8, '3']],
        [[1, 'fail'], [-2, 'test'], [9, 'exit'], [9, '1']],
        [[6, 'agent'], [5, 'working'], [8, '04:12']],
    ];

    function tone(index: number): string {
        if (index === -1) return palette.accent;
        if (index === -2) return palette.termFg;
        return palette.ansi[index] ?? palette.termFg;
    }
</script>

<div
    class="tpv"
    class:tpv-large={size === 'large'}
    style={previewStyle(palette)}
    role="img"
    aria-label={label}
    data-preview-size={size}
>
    <div class="tpv-head">
        <span class="tpv-mark"></span>
        <span class="tpv-bar" style="width:22%"></span>
        {#if palette.ascii}<span class="tpv-ascii" aria-hidden="true">░▒▓╞═══╪───</span>{/if}
        <span class="tpv-grow"></span>
        <span class="tpv-bar tpv-bar-dim" style="width:12%"></span>
    </div>
    <div class="tpv-body">
        <div class="tpv-side">
            {#each [34, 58, 46, 40, 52] as width, index (index)}
                <span class="tpv-row" class:tpv-row-on={index === 1}>
                    <span class="tpv-led" style={`background:${[palette.success, palette.success, palette.warning, palette.muted, palette.danger][index]}`}></span>
                    <span class="tpv-bar tpv-bar-dim" style={`width:${width}%`}></span>
                </span>
            {/each}
        </div>
        <div class="tpv-term">
            {#if art && !artFailed}
                <img class="tpv-art" src={art} alt="" loading="lazy" decoding="async" onerror={() => (artFailed = true)} />
            {/if}
            {#if size === 'large'}
                {#each TEXT_ROWS as row, index (index)}
                    <span class="tpv-line">
                        {#each row as [ansi, text], at (at)}<span style={`color:${tone(ansi)}`}>{text}</span>{/each}
                    </span>
                {/each}
                <span class="tpv-line"><span style={`color:${palette.accent}`}>$</span><span class="tpv-cursor"></span></span>
            {:else}
                {#each BAR_ROWS as row, index (index)}
                    <span class="tpv-line">
                        {#each row as [ansi, width], at (at)}<span class="tpv-seg" style={`width:${width}%;background:${tone(ansi)}`}></span>{/each}
                    </span>
                {/each}
                <span class="tpv-line"><span class="tpv-cursor"></span></span>
            {/if}
        </div>
    </div>
    <div class="tpv-status">
        <span class="tpv-led" style={`background:${palette.success}`}></span>
        <span class="tpv-led" style={`background:${palette.warning}`}></span>
        <span class="tpv-led" style={`background:${palette.danger}`}></span>
        <span class="tpv-grow"></span>
        <span class="tpv-bar tpv-bar-dim" style="width:16%"></span>
    </div>
</div>

<style>
    .tpv {
        container-type: inline-size;
        position: relative;
        display: grid;
        grid-template-rows: 11% 1fr 9%;
        aspect-ratio: 16 / 10;
        width: 100%;
        overflow: hidden;
        border: 1px solid var(--p-border);
        border-radius: 3px;
        background: var(--p-page);
        color: var(--p-fg);
        font-family: var(--font-mono, monospace);
    }

    .tpv:not(.tpv-large) {
        aspect-ratio: 16 / 9;
    }

    .tpv-head,
    .tpv-status {
        display: flex;
        align-items: center;
        gap: 2.5cqw;
        padding: 0 3cqw;
        min-width: 0;
        overflow: hidden;
    }

    .tpv-head {
        background: var(--p-header);
        border-bottom: 1px solid var(--p-border);
    }

    .tpv-status {
        background: var(--p-panel);
        border-top: 1px solid var(--p-border);
    }

    .tpv-mark {
        flex: 0 0 auto;
        width: 3cqw;
        height: 3cqw;
        border-radius: 0.5cqw;
        background: var(--p-accent);
    }

    .tpv-bar {
        flex: 0 0 auto;
        display: block;
        height: 1.4cqw;
        border-radius: 1px;
        background: var(--p-fg);
        opacity: 0.85;
    }

    .tpv-bar-dim {
        background: var(--p-muted);
        opacity: 0.8;
    }

    .tpv-grow {
        flex: 1 1 auto;
    }

    .tpv-ascii {
        flex: 0 1 auto;
        overflow: hidden;
        white-space: nowrap;
        font-size: 3cqw;
        line-height: 1;
        color: var(--p-accent);
    }

    .tpv-body {
        display: grid;
        grid-template-columns: 26% 1fr;
        min-height: 0;
    }

    .tpv-side {
        display: flex;
        flex-direction: column;
        gap: 2cqw;
        padding: 3cqw 2.5cqw;
        background: var(--p-panel);
        border-right: 1px solid var(--p-border);
        min-width: 0;
    }

    .tpv-row {
        display: flex;
        align-items: center;
        gap: 1.6cqw;
        padding: 0.8cqw 1cqw;
        border-left: 0.6cqw solid transparent;
    }

    .tpv-row-on {
        border-left-color: var(--p-accent);
        background: color-mix(in srgb, var(--p-accent) 16%, transparent);
    }

    .tpv-led {
        flex: 0 0 auto;
        width: 1.8cqw;
        height: 1.8cqw;
        border-radius: 50%;
    }

    .tpv-term {
        position: relative;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
        gap: 2.4cqw;
        padding: 3.5cqw 4cqw;
        background: var(--p-term-bg);
        color: var(--p-term-fg);
        min-width: 0;
        overflow: hidden;
    }

    .tpv-art {
        position: absolute;
        right: 0;
        top: 0;
        width: 62%;
        height: 100%;
        object-fit: cover;
        opacity: 0.38;
        pointer-events: none;
        mask-image: linear-gradient(to right, transparent, black 45%);
    }

    .tpv-large .tpv-art {
        width: 100%;
        opacity: 0.22;
        mask-image: none;
    }

    .tpv-line {
        position: relative;
        display: flex;
        align-items: center;
        gap: 1.6cqw;
        min-height: 1.4cqw;
        white-space: nowrap;
    }

    .tpv-seg {
        display: block;
        height: 1.4cqw;
        border-radius: 1px;
    }

    .tpv-large .tpv-term {
        gap: 1.4cqw;
        font-size: 3.1cqw;
        line-height: 1.25;
    }

    .tpv-cursor {
        display: block;
        width: 1.6cqw;
        height: 2.6cqw;
        background: var(--p-cursor);
    }
</style>
