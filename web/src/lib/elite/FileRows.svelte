
<script lang="ts">
    import type { Seg } from './file-rows';

    interface Row {
        key: string;
        id: string;
        lines: Seg[][];
        isNew: boolean;
        label: string;
    }

    const { rows, sel }: { rows: Row[]; sel: string | null } = $props();
</script>

{#each rows as r (r.key)}
    <div class="fa-row" class:sel={r.id === sel} class:is-new={r.isNew} class:tagged={r.lines[0]?.some((s) => s.c === 'fa-bx' && s.s === '[x]')} role="option" id={`fa-${r.id.replace(/[^a-z0-9_-]/gi, '_')}`} data-id={r.id} aria-selected={r.id === sel} aria-label={r.label}>
        {#each r.lines as line}
            <div class="fa-l">{#each line as s}<span class={s.c || undefined} data-kind={s.kind} data-tag={s.c === 'fa-bx' ? '' : undefined} aria-hidden={s.c === 'fa-bx' ? 'true' : undefined}>{s.s}</span>{/each}</div>
        {/each}
    </div>
{/each}
