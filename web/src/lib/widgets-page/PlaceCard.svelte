
<script lang="ts">
    import '../../opscenter/ui/rank-panel.css';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import GroupGlyph from './GroupGlyph.svelte';
    import WidgetTile from './WidgetTile.svelte';
    import type { Translate } from '../sessions/types';
    import type { PlaceDef } from './places';
    import type { PlaceRow } from './places-state.svelte';
    import { drag, endDrag } from './places-drag.svelte';

    interface Looked {
        name: string;
        icon: string;
        tone: string;
        group: string;
    }

    interface Props {
        def: PlaceDef;
        rows: readonly PlaceRow[];
        boards: readonly { id: string; name: string }[];
        board: string;
        chosen: boolean;
        accept: 'yes' | 'have' | 'no' | null;
        lookup: (widget: string) => Looked | null;
        t: Translate;
        onPick: () => void;
        onAdd: (anchor: HTMLElement) => void;
        onOpen: (widget: string) => void;
        onRemove: (row: PlaceRow) => void;
        onMove: (row: PlaceRow, to: number) => void;
        onDropWidget: (widget: string) => void;
        onBoard: (id: string) => void;
    }

    const { def, rows, boards, board, chosen, accept, lookup, t, onPick, onAdd, onOpen, onRemove, onMove, onDropWidget, onBoard }: Props = $props();

    const isBoard = $derived(def.id === 'board');
    const label = $derived(t(`widgets.places.${def.id}.label`));
    const items = $derived(isBoard ? boards.map((b) => ({ key: b.id, widget: '' })) : rows);
    let body: HTMLElement | undefined = $state();
    let hidden = $state(0);
    let over = $state(false);

    const CAP = 4;

    function measure(): void {
        if (!body) return;
        let height = 0;
        for (const row of Array.from(body.children).slice(0, CAP)) height += (row as HTMLElement).offsetHeight;
        if (height > 0) body.style.maxHeight = `${height}px`;
        const rowH = body.firstElementChild instanceof HTMLElement ? body.firstElementChild.offsetHeight || 34 : 34;
        hidden = Math.max(0, Math.ceil((body.scrollHeight - body.clientHeight - body.scrollTop - 2) / rowH));
    }
    $effect(() => {
        void items.length;
        requestAnimationFrame(measure);
    });

    function takes(): boolean {
        return drag.widget !== null ? accept === 'yes' : drag.row !== null && drag.row.place === def.id && !isBoard;
    }

    function over_(event: DragEvent): void {
        if (!takes()) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = drag.widget ? 'copy' : 'move';
        over = true;
        if (drag.row) {
            const row = (event.target as HTMLElement).closest<HTMLElement>('[data-row]');
            const key = row?.dataset['row'];
            if (row && key && key !== drag.row.key) {
                const box = row.getBoundingClientRect();
                drag.ins = { key, pos: event.clientY < box.top + box.height / 2 ? 'before' : 'after' };
            } else drag.ins = null;
        }
    }

    function dropped(event: DragEvent): void {
        event.preventDefault();
        over = false;
        if (drag.widget) {
            const widget = drag.widget;
            endDrag();
            onDropWidget(widget);
        } else if (drag.row && drag.row.place === def.id) {
            const moving = drag.row.key;
            const ins = drag.ins;
            endDrag();
            const from = rows.findIndex((row) => row.key === moving);
            let to = rows.length - 1;
            if (ins) {
                const at = rows.findIndex((row) => row.key === ins.key);
                to = ins.pos === 'before' ? at : at + 1;
                if (from < to) to -= 1;
            }
            const row = rows[from];
            if (row) onMove(row, to);
        }
    }

    function keydown(event: KeyboardEvent, row: PlaceRow, index: number): void {
        if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
            event.preventDefault();
            const to = Math.max(0, Math.min(rows.length - 1, index + (event.key === 'ArrowUp' ? -1 : 1)));
            if (to !== index) onMove(row, to);
        } else if (event.key === 'Delete' || event.key === 'Backspace') {
            event.preventDefault();
            onRemove(row);
        } else if (event.key === 'Enter') {
            event.preventDefault();
            onOpen(row.widget);
        }
    }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<section
    class="oc-rank wp-place"
    data-place={def.id}
    data-pl={def.id}
    data-accept={accept ?? undefined}
    class:is-over={over}
    role="group"
    aria-label={label}
    data-chosen={chosen ? '' : undefined}
    data-more={hidden > 0 ? '' : undefined}
    ondragover={over_}
    ondragleave={(event) => {
        if (!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node | null)) over = false;
    }}
    ondrop={dropped}
>
    <div class="wp-place__head">
        <button type="button" class="wp-place__pick" aria-pressed={chosen} title={t('widgets.places.pick', { place: label })} onclick={onPick}>
            <span class="wp-pmark" data-pl={def.id}>{def.mark}</span>
            <h3 class="wp-place__name oc-rank__label">
                <span class="t-name">{label}</span>
                <span class="t-drop">{isBoard ? t('widgets.places.drop_board', { name: boards.find((b) => b.id === board)?.name ?? '' }) : t('widgets.places.drop_here')}</span>
                <span class="t-have">{t('widgets.places.already')}</span>
                <span class="t-no">{t('widgets.places.no_fit')}</span>
            </h3>
        </button>
        <button
            type="button"
            class="wp-place__add"
            aria-label={t('widgets.places.add_to_place', { place: label })}
            title={t('widgets.places.add_to_place', { place: label })}
            aria-haspopup="menu"
            onclick={(event) => {
                event.stopPropagation();
                onAdd(event.currentTarget as HTMLElement);
            }}
        ><Icon name="plus" size={12} /></button>
    </div>
    <div class="wp-place__wrap">
        <div class="wp-place__body" role="list" aria-label={label} tabindex="-1" bind:this={body} onscroll={measure}>
            {#if items.length === 0}<div class="wp-place__empty">{t('widgets.places.empty')}</div>{/if}
            {#if isBoard}
                {#each boards as one, index (one.id)}
                    <!-- svelte-ignore a11y_no_noninteractive_element_interactions, a11y_no_noninteractive_tabindex -->
                    <div class="oc-rank__row wp-row is-board" role="listitem" tabindex="0" data-row={one.id} aria-current={chosen && board === one.id ? 'true' : undefined} aria-label={t('widgets.places.board.named', { name: one.name })}
                        onclick={() => onBoard(one.id)} onkeydown={(event) => event.key === 'Enter' && onBoard(one.id)}>
                        <span class="oc-rank__num">{index + 1}</span>
                        <span class="wp-tile wp-tile--board" data-pl="board" style="--tile-size: 20px; width: 20px; height: 20px" aria-hidden="true"><GroupGlyph name="grid" size={12} /></span>
                        <span class="oc-rank__name">{one.name}</span>
                        <span></span>
                    </div>
                {/each}
            {:else}
                {#each rows as row, index (row.key)}
                    {@const one = lookup(row.widget)}
                    {#if one}
                        <!-- svelte-ignore a11y_no_noninteractive_element_interactions, a11y_no_noninteractive_tabindex -->
                        <div
                            class="oc-rank__row wp-row"
                            role="listitem"
                            tabindex="0"
                            draggable="true"
                            data-row={row.key}
                            data-ins={drag.ins?.key === row.key ? drag.ins.pos : undefined}
                            class:is-lifted={drag.row?.key === row.key}
                            aria-label={t('widgets.places.row_label', { name: one.name, n: index + 1, total: rows.length })}
                            onclick={() => onOpen(row.widget)}
                            onkeydown={(event) => keydown(event, row, index)}
                            ondragstart={(event) => {
                                drag.row = { place: def.id, key: row.key };
                                if (event.dataTransfer) {
                                    event.dataTransfer.effectAllowed = 'move';
                                    event.dataTransfer.setData('text/plain', row.key);
                                }
                            }}
                            ondragend={endDrag}
                        >
                            <span class="oc-rank__num">{index + 1}</span>
                            <WidgetTile id={row.widget} icon={one.icon} group={one.group} size={20} />
                            <span class="oc-rank__name">{one.name}</span>
                            <button type="button" class="wp-row__x" title={t('widgets.places.take_out', { name: one.name, place: label })} aria-label={t('widgets.places.take_out', { name: one.name, place: label })}
                                onclick={(event) => { event.stopPropagation(); onRemove(row); }}><Icon name="close" size={12} /></button>
                        </div>
                    {/if}
                {/each}
            {/if}
        </div>
        <div class="wp-place__more" aria-hidden="true" hidden={hidden === 0}><span>{t('widgets.places.more', { n: hidden })}</span><Icon name="chevron-down" size={10} /></div>
    </div>
</section>
