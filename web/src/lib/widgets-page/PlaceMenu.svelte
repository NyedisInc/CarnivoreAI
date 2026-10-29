
<script lang="ts" module>
export interface MenuHead {
    head: string;
}
export interface MenuRow {
    id: string;
    label: string;
    sub?: string;
    key?: string;
    disabled?: boolean;
    mark?: { letter: string; place: string };
    widget?: { id: string; icon: string; tone: string };
    run?: () => void;
}
export type MenuEntry = MenuHead | MenuRow;
</script>

<script lang="ts">
    import { onMount, tick } from 'svelte';
    import WidgetIcon from '../../opscenter/ui/WidgetIcon.svelte';
    import { t } from '../i18n/index.svelte';

    interface Props {
        anchor: HTMLElement;
        entries: readonly MenuEntry[];
        label: string;
        align?: 'left' | 'right';
        onClose: () => void;
    }

    const { anchor, entries, label, align = 'left', onClose }: Props = $props();

    let panel: HTMLElement | undefined = $state();
    let findInput: HTMLInputElement | undefined = $state();
    let query = $state('');
    let left = $state(0);
    let top = $state(0);
    let maxH = $state(380);

    const isRow = (entry: MenuEntry): entry is MenuRow => 'id' in entry;
    const rows = $derived(entries.filter(isRow));
    const finding = $derived(rows.length > 9);
    const needle = $derived(query.trim().toLowerCase());
    const shown = $derived(
        needle === '' ? entries : entries.filter((entry): entry is MenuRow => isRow(entry) && `${entry.label} ${entry.sub ?? ''}`.toLowerCase().includes(needle)),
    );

    function place(): void {
        if (!panel) return;
        const box = anchor.getBoundingClientRect();
        const vv = window.visualViewport;
        const vw = vv ? vv.width : window.innerWidth;
        const vh = vv ? vv.height : window.innerHeight;
        const edge = 8;
        maxH = Math.max(160, Math.min(380, vh - 2 * edge));
        const pw = panel.offsetWidth;
        const ph = Math.min(panel.offsetHeight, maxH);
        let y = box.bottom + 4;
        if (y + ph > vh - edge && box.top - 4 - ph >= edge) y = box.top - 4 - ph;
        else if (y + ph > vh - edge) y = Math.max(edge, vh - edge - ph);
        const x = align === 'right' ? box.right - pw : box.left;
        left = Math.max(edge, Math.min(x, vw - edge - pw));
        top = y;
    }

    function items(): HTMLElement[] {
        return panel ? [...panel.querySelectorAll<HTMLElement>('.session-row-menu__item')] : [];
    }

    function close(back = true): void {
        anchor.setAttribute('aria-expanded', 'false');
        onClose();
        if (back) {
            try { anchor.focus({ preventScroll: true }); } catch {  }
        }
    }

    function pick(row: MenuRow): void {
        if (row.disabled) return;
        close(false);
        row.run?.();
    }

    onMount(() => {
        anchor.setAttribute('aria-expanded', 'true');
        const away = (event: PointerEvent): void => {
            const target = event.target as Node;
            if (panel && !panel.contains(target) && !anchor.contains(target)) close(false);
        };
        const key = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                close();
                return;
            }
            const list = items();
            const at = list.indexOf(document.activeElement as HTMLElement);
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                (list[at + 1] ?? list[0])?.focus();
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                (list[at - 1] ?? list[list.length - 1])?.focus();
            }
        };
        const scrolled = (event: Event): void => {
            if (panel && !panel.contains(event.target as Node)) close(false);
        };
        const gone = (): void => close(false);
        document.addEventListener('pointerdown', away, true);
        document.addEventListener('keydown', key, true);
        document.addEventListener('scroll', scrolled, true);
        window.addEventListener('resize', gone);
        window.addEventListener('blur', gone);
        void tick().then(() => {
            place();
            (findInput ?? items().find((el) => el.getAttribute('aria-disabled') !== 'true'))?.focus({ preventScroll: true });
        });
        return () => {
            document.removeEventListener('pointerdown', away, true);
            document.removeEventListener('keydown', key, true);
            document.removeEventListener('scroll', scrolled, true);
            window.removeEventListener('resize', gone);
            window.removeEventListener('blur', gone);
        };
    });
</script>

<div bind:this={panel} class="session-row-menu popup-focus wp-menu" role="menu" aria-label={label} style:left="{left}px" style:top="{top}px" style:max-height="{maxH}px">
    {#if finding}
        <div class="session-row-menu__find oc-focus-host">
            <input class="oc-field" type="search" bind:this={findInput} bind:value={query} placeholder={t('widgets.places.menu.find')} aria-label={t('widgets.places.menu.find_label')} />
        </div>
    {/if}
    <div class="wp-menu__list" role="none">
        {#each shown as entry, index (isRow(entry) ? entry.id : `head:${index}`)}
            {#if isRow(entry)}
                <button
                    type="button"
                    class="session-row-menu__item"
                    role="menuitem"
                    tabindex="-1"
                    data-node={entry.id}
                    aria-disabled={entry.disabled ? 'true' : undefined}
                    data-tooltip={entry.disabled ? entry.sub : undefined}
                    {...(entry.disabled && entry.sub ? { 'aria-description': entry.sub } : {})}
                    onclick={(event) => { event.stopPropagation(); pick(entry); }}
                >
                    <span class="session-row-menu__icon">
                        {#if entry.mark}<span class="wp-pmark" data-pl={entry.mark.place}>{entry.mark.letter}</span>
                        {:else if entry.widget}<span class="wp-menu__wicon" style={`color: var(--${entry.widget.tone})`}><WidgetIcon name={entry.widget.icon} widget={entry.widget.id} size={14} /></span>{/if}
                    </span>
                    <span class="session-row-menu__label">{entry.label}</span>
                    <span class="session-row-menu__key">{entry.key ?? ''}</span>
                    {#if entry.sub && !entry.disabled}<span class="session-row-menu__reason">{entry.sub}</span>{/if}
                </button>
            {:else if needle === ''}
                <div class="session-row-menu__head">{entry.head}</div>
            {/if}
        {/each}
        {#if rows.length > 0 && shown.filter(isRow).length === 0}<div class="session-row-menu__none">{t('widgets.places.menu.nothing')}</div>{/if}
    </div>
</div>
