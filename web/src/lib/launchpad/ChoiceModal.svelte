<!-- the home screen -->
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import { PROJECT_CREATE_KEYS } from '../../../../client/js/labels/project-create.js';
    import type { Translate } from '../sessions/types';
    import type { ChoiceItem } from './modal-types';
    import ModalShell from './ModalShell.svelte';
    import Button from '../base/Button.svelte';
    import List from '../base/List.svelte';
    import ListRow from '../base/ListRow.svelte';

    interface Props {
        title: string;
        hint?: string | null;
        items?: ChoiceItem[];
        /* there is nothing */
        emptyMessage?: string | null;
        emptyKind?: string;
        t?: Translate;
        close: (value: string | null) => void;
    }

    let {
        title,
        hint = null,
        items = [],
        emptyMessage = null,
        emptyKind = 'info',
        t = reactiveT,
        close,
    }: Props = $props();

    const selectable = $derived(
        items.map((item, i) => (item.disabled ? -1 : i)).filter((i) => i >= 0),
    );

    let active = $state(-1);
    const rowEls: Array<HTMLDivElement | null> = $state([]);

    $effect(() => {
        if (active === -1 && selectable.length) active = selectable[0] ?? -1;
    });

    $effect(() => {
        if (active < 0) return;
        const row = rowEls[active];
        if (row && typeof row.scrollIntoView === 'function') {
            row.scrollIntoView({ block: 'nearest' });
        }
    });

    function step(direction: number): void {
        if (!selectable.length) return;
        const at = selectable.indexOf(active);
        const next = at < 0 ? 0 : (at + direction + selectable.length) % selectable.length;
        active = selectable[next] ?? active;
    }

    function choose(index: number): void {
        const item = items[index];
        if (!item || item.disabled) return;
        close(item.key);
    }

    $effect(() => {
        const onKey = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                close(null);
                return;
            }
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                event.stopPropagation();
                step(1);
                return;
            }
            if (event.key === 'ArrowUp') {
                event.preventDefault();
                event.stopPropagation();
                step(-1);
                return;
            }
            if (event.key === 'Enter') {
                event.preventDefault();
                event.stopPropagation();
                if (active >= 0) choose(active);
            }
        };
        document.addEventListener('keydown', onKey, true);
        return () => document.removeEventListener('keydown', onKey, true);
    });
</script>

<ModalShell {title} onCancel={() => close(null)}>
    <List class="folder-picker-list" tabindex={-1} label={title}>
        {#if items.length}
            {#each items as item, i (item.key)}
                
                <ListRow
                    wrap
                    selected={i === active}
                    primary={item.label}
                    secondary={item.disabled && item.reason ? item.reason : item.sub || undefined}
                    data-choice-index={i}
                    aria-disabled={item.disabled ? 'true' : undefined}
                    onclick={() => choose(i)}
                    {@attach (el: Element) => {
                        rowEls[i] = el as HTMLDivElement;
                        return () => {
                            rowEls[i] = null;
                        };
                    }}
                />
            {/each}
        {:else}
            <div class="folder-picker-empty folder-picker-empty--{emptyKind}">
                {emptyMessage || t(PROJECT_CREATE_KEYS.choiceEmptyFallback)}
            </div>
        {/if}
    </List>
    <div class="modal-description">
        {items.length
            ? hint || t(PROJECT_CREATE_KEYS.choiceHint)
            : t(PROJECT_CREATE_KEYS.choiceEmptyHint)}
    </div>
    {#snippet footer()}
        <Button data-choice-cancel onclick={() => close(null)}>
            {items.length ? t(PROJECT_CREATE_KEYS.cancel) : t(PROJECT_CREATE_KEYS.choiceOk)}
        </Button>
    {/snippet}
</ModalShell>
