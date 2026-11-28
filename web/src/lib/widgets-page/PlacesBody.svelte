<!-- the reading pane -->
<script lang="ts">
    import { Button } from '../base';
    import { onMount } from 'svelte';
    import type { Translate } from '../sessions/types';
    import PlaceMenu, { type MenuEntry } from './PlaceMenu.svelte';
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import type { ManagerStatus } from '../manager-frame/types';
    import { sizeNameKey } from '../../opscenter/widgets/named-sizes';
    import { infoKeys } from '../../opscenter/widgets/info/widget-info';
    import { WIDGET_CATEGORIES } from '../../opscenter/widgets/types';
    import type { WidgetItem } from './widgets-adapter';
    import PlaceCard from './PlaceCard.svelte';
    import PlaceDock from './PlaceDock.svelte';
    import WidgetCard, { type Mark } from './WidgetCard.svelte';
    import { PLACES, boardCell, fits, missingReason, placeDef, placeName, placedSize, type PlaceId } from './places';
    import { drag, endDrag } from './places-drag.svelte';
    import { boardList, boardsHolding, liveBoardId, placedIn, rowsOf, startPlaceStores } from './places-state.svelte';
    import { fitsIn, groupName as nameOfGroup, isOn, matchedItems, passes } from './places-lens';
    import { addToPlace, moveInPlace, removeFromPlace } from './places-writes';
    import { setPlace, view } from './places-view.svelte';
    import { PREVIEW_CAP } from './preview-slots.svelte';

    interface Props {
        items: readonly WidgetItem[];
        query: string;
        status: ManagerStatus;
        t: Translate;
        selectedId: string | null;
        onOpen: (id: string) => void;
        live: boolean;
        onRetry: () => void;
        onClear: () => void;
        limits?: readonly string[];
        openMenu?: (anchor: HTMLElement, id: string) => void;
    }

    let { items, query, status, t, selectedId, onOpen, live, onRetry, onClear, limits = [], openMenu = $bindable() }: Props = $props();

    onMount(startPlaceStores);

    const byId = $derived(new Map(items.map((item) => [item.id, item])));
    const boards = $derived(boardList());
    const board = $derived(boards.some((one) => one.id === view.board) ? view.board : liveBoardId());
    const boardName = $derived(boards.find((one) => one.id === board)?.name ?? '');
    const heldIn = (item: WidgetItem, place: PlaceId, boardId: string = board): boolean => placedIn(item.id, place, boardCell(item.manifest), boardId);
    const groupName = (group: string): string => nameOfGroup(group, t);

    function lookup(id: string): { name: string; icon: string; tone: string; group: string } | null {
        const item = byId.get(id);
        return item ? { name: item.name, icon: item.manifest.icon, tone: item.manifest.iconTone, group: item.manifest.category } : null;
    }

    const matched = $derived(matchedItems(items, query));

    const sections = $derived.by(() => {
        const shown = matched.filter((item) => passes(item));
        const byName = (a: WidgetItem, b: WidgetItem): number => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
        const place = view.place;
        const rank = (item: WidgetItem): number => (place === 'any' || fitsIn(item, place) ? 0 : 1);
        if (view.sort === 'name') return shown.length ? [{ id: 'all', name: t('widgets.places.group.all'), items: [...shown].sort(byName), of: items.length }] : [];
        const list = WIDGET_CATEGORIES.map((group) => ({ id: group, name: groupName(group), items: shown.filter((item) => item.manifest.category === group).sort((a, b) => rank(a) - rank(b) || byName(a, b)), of: items.filter((item) => item.manifest.category === group).length })).filter((one) => one.items.length > 0);
        return place === 'any' ? list : list.map((one, index) => ({ one, index, n: one.items.filter((item) => fitsIn(item, place)).length })).sort((a, b) => Number(b.n > 0) - Number(a.n > 0) || a.index - b.index).map((x) => x.one);
    });

    let podiumEl = $state<HTMLElement | undefined>();
    let menu = $state<{ anchor: HTMLElement; entries: MenuEntry[]; label: string; align: 'left' | 'right' } | null>(null);

    function add(item: WidgetItem, place: PlaceId, boardId: string = board): void {
        if (!fitsIn(item, place) || heldIn(item, place, boardId)) return;
        void addToPlace(item.id, item.name, place, place === 'board' ? boardId : null, boardCell(item.manifest), t);
    }

    function placeMenu(item: WidgetItem): MenuEntry[] {
        return PLACES.map((def): MenuEntry => {
            const label = def.id === 'board' ? t('widgets.places.menu.dashboards', { name: boardName }) : placeName(def.id, t);
            const fit = fitsIn(item, def.id);
            const have = heldIn(item, def.id);
            const noCell = def.id === 'board' && boardCell(item.manifest) === null;
            const size = placedSize(item.manifest, def.id);
            const mark = { letter: def.mark, place: def.id };
            if (have) return { id: def.id, label, mark, disabled: true, sub: t('widgets.places.already') };
            if (!fit) return { id: def.id, label, mark, disabled: true, sub: missingReason(item.manifest, isOn(item), def.id, t) };
            if (noCell) return { id: def.id, label, mark, disabled: true, sub: t('widgets.places.menu.board_cell') };
            return { id: def.id, label, mark, sub: size ? t('widgets.places.menu.fits_as', { size: t(sizeNameKey(size)) }) : undefined, run: () => add(item, def.id) };
        });
    }

    function showPlaceMenu(anchor: HTMLElement, id: string): void {
        const item = byId.get(id);
        if (item) menu = { anchor, entries: placeMenu(item), label: t('widgets.places.menu.label', { name: item.name }), align: 'right' };
    }
    // svelte-ignore state_referenced_locally
    openMenu = showPlaceMenu;

    function showAddMenu(anchor: HTMLElement, place: PlaceId): void {
        const list = items.filter((item) => fitsIn(item, place) && !heldIn(item, place) && (place !== 'board' || boardCell(item.manifest) !== null));
        const name = place === 'board' ? t('widgets.places.board.named', { name: boardName }) : placeName(place, t);
        const entries: MenuEntry[] = [{ head: t('widgets.places.menu.head', { place: name }) }];
        if (list.length === 0) entries.push({ id: 'none', label: t('widgets.places.menu.none'), disabled: true });
        for (const item of list) entries.push({ id: item.id, label: item.name, key: groupName(item.manifest.category), widget: { id: item.id, icon: item.manifest.icon, tone: item.manifest.iconTone }, run: () => add(item, place) });
        menu = { anchor, entries, label: t('widgets.places.add_to_place', { place: name }), align: 'left' };
    }

    function marksOf(item: WidgetItem): Mark[] {
        return PLACES.map((def) => {
            if (def.id === 'board') {
                const names = boardsHolding(boardCell(item.manifest)).map((one) => one.name);
                return { id: def.id, on: names.length > 0, here: names.length > 0 && view.place === 'board', word: names.length ? t('widgets.places.card.mark_board_in', { boards: names.join(` ${t('widgets.places.and')} `) }) : t('widgets.places.card.mark_board_none') };
            }
            const held = heldIn(item, def.id);
            return { id: def.id, on: held, here: held && view.place === def.id, word: t(held ? 'widgets.places.card.mark_in' : 'widgets.places.card.mark_not', { place: placeName(def.id, t) }) };
        });
    }

    function cardMain(item: WidgetItem, anchor: HTMLElement): void {
        if (view.place === 'any') showPlaceMenu(anchor, item.id);
        else add(item, view.place);
    }

    function acceptFor(place: PlaceId): 'yes' | 'have' | 'no' | null {
        if (drag.widget) {
            const item = byId.get(drag.widget);
            if (!item || !fitsIn(item, place) || (place === 'board' && boardCell(item.manifest) === null)) return 'no';
            return heldIn(item, place) ? 'have' : 'yes';
        }
        return drag.row ? (drag.row.place === place && place !== 'board' ? 'yes' : 'no') : null;
    }

    function removeRow(place: Exclude<PlaceId, 'board'>, row: { key: string; widget: string }): void {
        const item = byId.get(row.widget);
        if (item) void removeFromPlace(item.id, item.name, place, row.key, null, null, t);
    }

    const nothing = $derived(sections.length === 0);
</script>

<div class="wp-body">
{#if status.kind === 'loading'}
    <div class="oc-page__scroll"><div class="oc-page__main"><p class="oc-page__state" role="status">{t(MANAGER_KEYS.loading)}</p></div></div>
{:else if status.kind === 'error'}
    <div class="oc-page__scroll"><div class="oc-page__main">
        <div class="oc-page__error" role="alert">
            <p class="oc-page__error-title">{t(MANAGER_KEYS.errorTitle)}</p>
            <p class="oc-page__error-detail">{status.message}</p>
            <Button onclick={onRetry}>{t(MANAGER_KEYS.errorRetry)}</Button>
        </div>
    </div></div>
{:else}
    <div class="oc-page__scroll">
        <div class="oc-page__main wp-main" data-wp-preview-cap={live ? PREVIEW_CAP : undefined}>
            <div class="wp-sectionlabel"><span class="wp-sectionlabel__label">{t('widgets.places.title')}</span><span class="wp-sectionlabel__sub">{t('widgets.places.sub')}</span></div>
            <div class="wp-stick">
                <div class="wp-podium" bind:this={podiumEl}>
                    {#each PLACES as def (def.id)}
                        <PlaceCard
                            {def}
                            rows={def.id === 'board' ? [] : rowsOf(def.id)}
                            {boards}
                            {board}
                            chosen={view.place === def.id}
                            accept={acceptFor(def.id)}
                            {lookup}
                            {t}
                            onPick={() => setPlace(view.place === def.id ? 'any' : def.id)}
                            onAdd={(anchor) => showAddMenu(anchor, def.id)}
                            onOpen={(widget) => onOpen(widget)}
                            onRemove={(row) => def.id !== 'board' && removeRow(def.id, row)}
                            onMove={(row, to) => {
                                const item = byId.get(row.widget);
                                if (item && def.id !== 'board') moveInPlace(def.id, row.key, to, item.name, t);
                            }}
                            onDropWidget={(widget) => {
                                const item = byId.get(widget);
                                if (item) add(item, def.id);
                            }}
                            onBoard={(id) => {
                                view.board = id;
                                setPlace('board');
                            }}
                        />
                    {/each}
                </div>
            </div>
            <PlaceDock
                podium={podiumEl}
                place={view.place}
                {boardName}
                accept={acceptFor}
                {t}
                onPick={setPlace}
                onDrop={(widget, place) => {
                    const item = byId.get(widget);
                    endDrag();
                    if (item) add(item, place);
                }}
            />
            {#if nothing}
                <div class="oc-page__empty pl-panel">
                    <p class="oc-page__empty-text">{items.length > 0 ? t(MANAGER_KEYS.emptyFiltered) : t('widgets.page.empty')}</p>
                    {#if items.length > 0}<Button onclick={onClear}>{t(MANAGER_KEYS.clear)}</Button>{/if}
                </div>
            {/if}
            {#each sections as section (section.id)}
                {@const fitting = view.place === 'any' ? 0 : section.items.filter((item) => fitsIn(item, view.place as PlaceId)).length}
                <section class="wp-group" data-wp-section={section.id}>
                    <h3 class="wp-sectionlabel"><span class="wp-sectionlabel__label">{section.name}</span><span class="wp-sectionlabel__sub">{view.place === 'any' ? t('widgets.places.group.count', { shown: section.items.length, all: section.of }) : t('widgets.places.group.fit', { place: placeName(view.place as PlaceId, t), fits: fitting, shown: section.items.length })}</span></h3>
                    <ul class="wp-grid">
                        {#each section.items as item (item.id)}
                            {@const place = view.place}
                            {@const fit = place === 'any' || fitsIn(item, place)}
                            {@const held = place !== 'any' && heldIn(item, place)}
                            <WidgetCard
                                id={item.id}
                                name={item.name}
                                group={item.manifest.category}
                                groupName={groupName(item.manifest.category)}
                                manifest={item.manifest}
                                brief={t(infoKeys(item.id).about)}
                                reason={fit ? null : missingReason(item.manifest, isOn(item), place as PlaceId, t)}
                                chip={!isOn(item) ? t('widgets.places.card.off') : held ? t('widgets.places.card.in', { place: placeName(place as PlaceId, t) }) : null}
                                marks={marksOf(item)}
                                here={place !== 'any'}
                                blocked={!fit || held}
                                enabled={isOn(item)}
                                selected={selectedId === item.id}
                                unread={false}
                                {live}
                                {t}
                                onOpen={() => onOpen(item.id)}
                                onMain={(anchor) => cardMain(item, anchor)}
                                onCaret={(anchor) => showPlaceMenu(anchor, item.id)}
                            />
                        {/each}
                    </ul>
                </section>
            {/each}
            {#if limits.length > 0}
                <div class="oc-page__limits" data-mgr-limits>
                    <span class="oc-label">{t(MANAGER_KEYS.limitsLabel)}</span>
                    {#each limits as limit (limit)}<p class="oc-notice oc-notice--muted">{limit}</p>{/each}
                </div>
            {/if}
        </div>
    </div>
{/if}
</div>

{#if menu}
    <PlaceMenu anchor={menu.anchor} entries={menu.entries} label={menu.label} align={menu.align} onClose={() => (menu = null)} />
{/if}
