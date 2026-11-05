<script lang="ts">
    import { onDestroy, onMount } from 'svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import Field from '../base/Field.svelte';
    import List from '../base/List.svelte';
    import ListRow from '../base/ListRow.svelte';
    import Tag from '../base/Tag.svelte';
    import { t } from '../i18n/index.svelte';
    import type { DeepGroup } from '../deepsearch/deepsearch-api';
    import { goTo } from '../nav-items/nav-items';
    import { commitChip, parseQuery, passesChips, rankText, type Chip } from './palette-query';
    import { createRanker, notePick, prunePicks, readPicks, writePicks } from './palette-rank';
    import { buildCorpus, drawerRows, emptyGroups, type PaletteItem, type PaletteKind } from './palette-sources';
    import { createDeepRunner } from './palette-deep';

    let { initial = '', onClose }: { initial?: string; onClose: () => void } = $props();

    const ICONS: Record<PaletteKind, string> = {
        session: 'session', project: 'folder', layout: 'layout', dashboard: 'chart', page: 'grid', browser: 'globe', file: 'files', help: 'help',
        setting: 'gear', theme: 'palette', action: 'bolt', search: 'deep-search',
    };
    const CHIP_SIGIL: Record<Chip['kind'], string> = { host: '@', project: '#', state: ':' };

    const corpus = buildCorpus();
    let picks = prunePicks(readPicks(), new Set([...corpus.items, ...corpus.actions].map((i) => i.id)));
    const ranker = createRanker<PaletteItem>(() => picks);
    const actionRanker = createRanker<PaletteItem>(() => picks);

    // svelte-ignore state_referenced_locally
    let value = $state(initial);
    let chips = $state<Chip[]>([]);
    let page = $state<PaletteItem | null>(null);
    let active = $state(0);
    let deepGroups = $state<DeepGroup[] | null>([]);
    let input: HTMLInputElement | HTMLTextAreaElement | null = $state(null);
    const deep = createDeepRunner((groups) => { deepGroups = groups; });

    const parsed = $derived(parseQuery(value));

    const suggestions = $derived.by((): PaletteItem[] => {
        const p = parsed.pending;
        if (!p || page) return [];
        return corpus.known[p.kind].filter((v) => v.startsWith(p.value)).slice(0, 8).map((v) => ({
            id: `chip:${p.kind}:${v}`, kind: p.kind === 'project' ? 'project' : 'search', title: CHIP_SIGIL[p.kind] + v,
            subtitle: t(`palette.chip.${p.kind}`), chip: v, run: () => undefined,
        } as PaletteItem));
    });

    const query = $derived(suggestions.length ? rankText(parsed) : parsed.text.trim());

    const groups = $derived.by((): { key: string; items: PaletteItem[] }[] => {
        if (page) {
            const list = page.actions?.() ?? [];
            return [{ key: 'palette.group.actions_for', items: query ? actionRanker.rank(list, query) : list }];
        }
        if (suggestions.length) return [{ key: 'palette.group.filters', items: suggestions }];
        if (parsed.mode === 'deep') return [{ key: 'palette.group.conversations', items: deepItems(deepGroups ?? []) }];
        if (parsed.mode === 'actions') return [{ key: 'palette.group.actions', items: query ? actionRanker.rank(corpus.actions, query) : corpus.actions }];
        if (!query && !chips.length) return emptyGroups(corpus);
        const pool = chips.length ? corpus.sessions.filter((s) => passesChips(s, chips)) : corpus.items;
        const found = query ? ranker.rank(pool, query) : pool.slice(0, 50);
        const tail: PaletteItem[] = query ? [{
            id: 'search:conversations', kind: 'search', title: t('palette.search_conversations', { text: query }), subtitle: '',
            run: () => undefined,
        }] : [];
        return [{ key: 'palette.group.results', items: [...found, ...tail] }];
    });

    const rows = $derived(groups.flatMap((g) => g.items));

    $effect(() => {
        if (parsed.mode === 'deep' && !page) deep.query(parsed.text);
        else deep.cancel();
    });
    $effect(() => {
        void rows;
        if (active >= rows.length) active = Math.max(0, rows.length - 1);
    });

    function deepItems(list: DeepGroup[]): PaletteItem[] {
        return list.map((g) => ({
            id: `conversation:${g.conversationId}`, kind: 'search' as const, title: g.firstPrompt || g.session || g.conversationId,
            subtitle: [g.session, g.project].filter(Boolean).join(' · '),
            run: () => {
                const row = drawerRows().find((r) => g.sessionUuid && r.session_uuid === g.sessionUuid);
                return row ? goTo({ kind: 'session', id: String(row.session_id || row.name), tmuxName: String(row.name) }) : false;
            },
        }));
    }

    function addChip(item: PaletteItem): void {
        const kind = item.id.startsWith('chip:') ? item.id.split(':')[1] as Chip['kind'] : 'project';
        if (!chips.some((c) => c.kind === kind && c.value === item.chip)) chips = [...chips, { kind, value: item.chip! }];
        value = parsed.pending ? value.slice(0, value.length - parsed.pending.raw.length) : '';
        active = 0;
        input?.focus();
    }

    function pick(item: PaletteItem | undefined, popout = false): void {
        if (!item) return;
        if (item.chip) return addChip(item);
        if (item.id === 'search:conversations') {
            value = `?${query}`;
            return;
        }
        notePick(picks, item.id, query, Date.now());
        writePicks(picks);
        onClose();
        void Promise.resolve(item.run({ popout })).catch((err: unknown) => console.error('palette: action failed', item.id, err));
    }

    function openPage(item: PaletteItem | undefined): boolean {
        if (!item?.actions) return false;
        page = item;
        value = '';
        active = 0;
        return true;
    }

    function onKey(e: KeyboardEvent): void {
        if (e.isComposing || e.keyCode === 229) return;
        const meta = e.metaKey || e.ctrlKey;
        let handled = true;
        if (e.key === 'Escape') {
            if (page) { page = null; value = ''; } else onClose();
        } else if (e.key === 'ArrowDown' || (e.ctrlKey && !e.metaKey && e.key === 'n')) {
            active = rows.length ? (active + 1) % rows.length : 0;
        } else if (e.key === 'ArrowUp' || (e.ctrlKey && !e.metaKey && e.key === 'p')) {
            active = rows.length ? (active - 1 + rows.length) % rows.length : 0;
        } else if (e.key === 'Enter') {
            pick(rows[active], e.metaKey);
        } else if (e.key === 'Tab' && !e.shiftKey) {
            const commit = commitChip(value, corpus.known);
            if (commit) {
                chips = [...chips, commit.chip];
                value = commit.rest;
            } else if (!openPage(rows[active])) handled = rows[active]?.chip ? (addChip(rows[active]!), true) : true;
        } else if (e.key === 'Backspace' && value === '' && (chips.length || page)) {
            if (chips.length) chips = chips.slice(0, -1); else page = null;
        } else if (e.metaKey && !e.shiftKey && !e.altKey && /^[1-5]$/.test(e.key)) {
            pick(rows[Number(e.key) - 1]);
        } else if (meta && e.key.toLowerCase() === 'k') {
            onClose();
        } else {
            handled = false;
        }
        if (handled) {
            e.preventDefault();
            e.stopPropagation();
        }
    }

    function marks(title: string, q: string): { text: string; hit: boolean }[] {
        const low = title.toLowerCase();
        const needle = q.toLowerCase();
        if (!needle) return [{ text: title, hit: false }];
        const at = low.indexOf(needle);
        if (at >= 0) return [{ text: title.slice(0, at), hit: false }, { text: title.slice(at, at + needle.length), hit: true }, { text: title.slice(at + needle.length), hit: false }];
        const out: { text: string; hit: boolean }[] = [];
        let j = 0;
        for (let i = 0; i < title.length; i += 1) {
            const hit = j < needle.length && low[i] === needle[j];
            if (hit) j += 1;
            const last = out[out.length - 1];
            if (last && last.hit === hit) last.text += title[i]; else out.push({ text: title[i]!, hit });
        }
        return out;
    }

    onMount(() => {
        globalThis.addEventListener('keydown', onKey, true);
        input?.focus();
    });
    onDestroy(() => {
        globalThis.removeEventListener('keydown', onKey, true);
        deep.cancel();
    });
</script>

<div class="cp-scrim" role="presentation" onmousedown={onClose}></div>
<div class="cp popup-focus" role="search" aria-label={t('palette.label')}>
    <div class="cp-bar">
        <span class="cp-title">{page ? page.title : t('palette.title')}</span>
        <Field
            variant="search"
            block
            bind:element={input}
            bind:value
            label={t(page ? 'palette.placeholder_actions' : 'palette.placeholder')}
            clearLabel={t('palette.clear')}
            onclear={() => { active = 0; }}
            spellcheck={false}
            autocomplete="off"
            role="combobox"
            aria-expanded="true"
            aria-controls="cp-list"
            aria-activedescendant={rows[active] ? `cp-row-${active}` : undefined}
            placeholder={t(page ? 'palette.placeholder_actions' : 'palette.placeholder')}
            oninput={() => { active = 0; }}
        >
            {#snippet lead()}
                {#each chips as chip (chip.kind + chip.value)}
                    <Tag>{CHIP_SIGIL[chip.kind]}{chip.value}</Tag>
                {/each}
            {/snippet}
        </Field>
    </div>
    <List class="cp-list" id="cp-list" role="listbox" label={t('palette.label')} density="roomy">
        {#each groups as group (group.key)}
            <div class="oc-label cp-group" role="presentation">{t(group.key, { name: page?.title ?? '' })}</div>
            {#each group.items as item (item.id)}
                {@const index = rows.indexOf(item)}
                <ListRow
                    id={`cp-row-${index}`}
                    role="option"
                    selected={index === active}
                    aria-selected={index === active}
                    muted={item.offline}
                    onmousemove={() => { active = index; }}
                    onmousedown={(e: MouseEvent) => { e.preventDefault(); pick(item, e.metaKey); }}
                >
                    {#snippet lead()}<Icon name={ICONS[item.kind]} size={14} />{/snippet}
                    {#snippet primary()}{#each marks(item.title, query) as part, i (i)}{#if part.hit}<mark>{part.text}</mark>{:else}{part.text}{/if}{/each}{/snippet}
                    {#snippet secondary()}{item.subtitle ?? ''}{/snippet}
                    {#snippet meta()}{index === active ? t('palette.key.enter') : index < 5 ? `cmd ${index + 1}` : ''}{/snippet}
                </ListRow>
            {/each}
        {:else}
            <div class="cp-empty" role="presentation">{deepGroups === null ? t('palette.searching') : t('palette.none')}</div>
        {/each}
    </List>
    <div class="cp-foot">{t('palette.footer')}</div>
</div>

<style>
    .cp-scrim {
        position: fixed;
        inset: 0;
        z-index: 9000;
        background: var(--oc-backdrop);
    }
    .cp {
        position: fixed;
        z-index: 9001;
        top: 12vh;
        left: 50%;
        transform: translateX(-50%);
        width: min(640px, calc(100vw - var(--oc-space-6)));
        max-height: 70vh;
        display: flex;
        flex-direction: column;
        font-family: var(--font-mono);
        color: var(--oc-text-primary);
    }
    .cp-bar {
        display: flex;
        align-items: center;
        gap: var(--oc-space-2);
        padding: var(--oc-space-2) var(--oc-space-3);
        background: var(--oc-ground-titlerow);
        box-shadow: inset 0 -1px 0 var(--oc-line-hairline);
    }
    .cp-bar :global(.oc-search) {
        flex: 1;
    }
    .cp-title {
        font-size: var(--oc-fs-micro);
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: var(--oc-orange);
        white-space: nowrap;
        max-width: 40%;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .cp :global(.cp-list) {
        overflow-y: auto;
        flex: 1;
    }
    .cp-group {
        padding: var(--oc-space-2) var(--oc-space-3) var(--oc-space-1);
    }
    .cp :global(.cp-list mark) {
        background: none;
        color: var(--oc-cyan);
    }
    .cp-empty {
        padding: var(--oc-space-3);
        font-size: var(--oc-fs-body);
        color: var(--oc-text-dim);
    }
    .cp-foot {
        padding: var(--oc-space-1-5) var(--oc-space-3);
        font-size: var(--oc-fs-micro);
        color: var(--oc-text-dim);
        box-shadow: inset 0 1px 0 var(--oc-line-hairline);
    }
    @media (max-width: 1023px) {
        .cp {
            top: 0;
            left: 0;
            transform: none;
            --pf-edge-top: transparent;
            --pf-edge-bottom: transparent;
            --pf-glow: transparent;
            --pf-sheen: transparent;
            box-shadow: none;
            width: 100vw;
            height: 100dvh;
            max-height: none;
            border-radius: 0;
        }
    }
</style>
