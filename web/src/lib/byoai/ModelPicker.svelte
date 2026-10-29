
<script lang="ts" module>
    let nextId = 0;
</script>

<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import './model-picker.css';
    import { nextOption as stepOption } from '../dropdown/listbox-nav';
    import { isSheetWidth, placePanel } from '../dropdown/placement';
    import ProviderMark from './ProviderMark.svelte';
    import { buildEntries, highlight, panelWidth, termsOf, type Entry, type PickItem } from './picker-logic';

    interface Props {
        t?: Translate;
        items: readonly PickItem[];
        value: string;
        onChange: (id: string) => void;
        label: string;
        placeholder?: string;
        disabled?: boolean;
        grouped?: boolean;
        allowCustom?: boolean;
        emptyLabel?: string;
        alpha?: boolean;
        loading?: boolean;
        dataAi?: string;
    }
    const { t = reactiveT, items, value, onChange, label, placeholder = '', disabled = false, grouped = true, allowCustom = false,
        emptyLabel = '', alpha = true, loading = false, dataAi = 'picker' }: Props = $props();

    const uid = `ai-pick-${(nextId += 1)}`;
    const ROW_H = 40;
    const HEAD_H = 26;
    const OVERSCAN = 6;

    let open = $state(false);
    let query = $state('');
    let touched = $state(false);
    let active = $state(0);
    let scrollTop = $state(0);
    let listH = $state(320);
    let panelStyle = $state('');
    let sheet = $state(false);
    let root: HTMLDivElement | undefined = $state();
    let input: HTMLInputElement | undefined = $state();
    let list: HTMLDivElement | undefined = $state();

    const all = $derived<readonly PickItem[]>(emptyLabel ? [{ id: '', text: emptyLabel, name: '', vendor: '', detail: '', flags: [] }, ...items] : items);
    const selected = $derived(all.find((i) => i.id === value && (value !== '' || emptyLabel !== '')));
    const terms = $derived(termsOf(touched ? query : ''));
    const entries = $derived<Entry[]>(buildEntries(all, touched ? query : '', { recent: t('settings.ai.picker.recent'), popular: t('settings.ai.picker.popular') }, { grouped, custom: allowCustom && touched, alpha }));
    const heights = $derived(entries.map((e) => (e.kind === 'header' ? HEAD_H : ROW_H)));
    const offsets = $derived.by(() => {
        const out: number[] = [];
        let sum = 0;
        for (const h of heights) { out.push(sum); sum += h; }
        out.push(sum);
        return out;
    });
    const total = $derived(offsets[offsets.length - 1] ?? 0);
    const optionCount = $derived(entries.filter((e) => e.kind !== 'header').length);
    const viewH = $derived(listH);
    const range = $derived.by(() => {
        let lo = 0;
        let hi = entries.length;
        while (lo < hi) { const mid = (lo + hi) >> 1; if ((offsets[mid + 1] ?? 0) <= scrollTop) lo = mid + 1; else hi = mid; }
        const first = Math.max(0, lo - OVERSCAN);
        let last = lo;
        while (last < entries.length && (offsets[last] ?? 0) < scrollTop + viewH) last += 1;
        return { first, last: Math.min(entries.length, last + OVERSCAN) };
    });
    const visible = $derived(entries.slice(range.first, range.last).map((entry, i) => ({ entry, index: range.first + i })));
    const shownText = $derived(touched ? query : (selected?.text ?? value));

    const posOf = (index: number): number => entries.slice(0, index + 1).filter((e) => e.kind !== 'header').length;
    const isOption = (index: number): boolean => entries[index] !== undefined && entries[index]!.kind !== 'header';
    const idOf = (index: number): string => `${uid}-o-${index}`;

    function place(): void {
        if (!root) return;
        const placed = placePanel(root.getBoundingClientRect(), { width: window.innerWidth, height: window.innerHeight }, isSheetWidth(),
            (boxWidth) => panelWidth(boxWidth, all, window.innerWidth));
        sheet = placed.sheet;
        listH = placed.room - 28;
        panelStyle = placed.style;
    }

    function reveal(index: number): void {
        if (!list) return;
        const top = offsets[index] ?? 0;
        const bottom = offsets[index + 1] ?? top;
        if (top < list.scrollTop) list.scrollTop = top;
        else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - (list.clientHeight || viewH);
        scrollTop = list.scrollTop;
    }

    const nextOption = (from: number, step: 1 | -1): number => stepOption(entries, from, step, isOption);

    function show(): void {
        if (open || disabled) return;
        touched = false;
        query = '';
        open = true;
        place();
        active = Math.max(0, nextOption(0, 1));
        scrollTop = 0;
        queueMicrotask(() => {
            input?.select();
            if (list) list.scrollTop = 0;
        });
    }

    function hide(): void {
        open = false;
        touched = false;
        query = '';
    }

    function choose(index: number): void {
        const entry = entries[index];
        if (!entry || entry.kind === 'header') return;
        const picked = entry.kind === 'custom' ? entry.id : entry.item.id;
        hide();
        onChange(picked);
    }

    function setActive(index: number): void {
        if (index < 0) return;
        active = index;
        reveal(index);
    }

    function onKey(e: KeyboardEvent): void {
        if (disabled) return;
        const key = e.key;
        if (!open) {
            if (key === 'ArrowDown' || key === 'ArrowUp' || key === 'Enter') { e.preventDefault(); show(); }
            return;
        }
        if (key === 'ArrowDown') { e.preventDefault(); setActive(nextOption(active + 1, 1) >= 0 ? nextOption(active + 1, 1) : active); }
        else if (key === 'ArrowUp') { e.preventDefault(); setActive(nextOption(active - 1, -1) >= 0 ? nextOption(active - 1, -1) : active); }
        else if (key === 'PageDown') { e.preventDefault(); setActive(nextOption(Math.min(entries.length - 1, active + 8), -1)); }
        else if (key === 'PageUp') { e.preventDefault(); setActive(nextOption(Math.max(0, active - 8), 1)); }
        else if (key === 'Home') { e.preventDefault(); setActive(nextOption(0, 1)); }
        else if (key === 'End') { e.preventDefault(); setActive(nextOption(entries.length - 1, -1)); }
        else if (key === 'Enter') { e.preventDefault(); choose(active); }
        else if (key === 'Escape') { e.preventDefault(); e.stopPropagation(); hide(); }
        else if (key === 'Tab') hide();
    }

    function onInput(e: Event & { currentTarget: HTMLInputElement }): void {
        if (!open) { open = true; place(); }
        touched = true;
        query = e.currentTarget.value;
        scrollTop = 0;
        if (list) list.scrollTop = 0;
        active = Math.max(0, nextOption(0, 1));
    }

    function onFocusOut(e: FocusEvent): void {
        if (open && !root?.contains(e.relatedTarget as Node | null)) hide();
    }

    $effect(() => {
        if (!open) return;
        const again = (): void => place();
        window.addEventListener('resize', again);
        window.addEventListener('scroll', again, true);
        return () => { window.removeEventListener('resize', again); window.removeEventListener('scroll', again, true); };
    });
</script>

<div class="ai-pick" class:ai-pick--open={open} class:ai-pick--lead={!!selected?.preset} bind:this={root} data-ai={dataAi} data-open={open}
    onfocusout={onFocusOut}>
    {#if selected?.preset}<span class="ai-pick__lead"><ProviderMark preset={selected.preset} size={14} /></span>{/if}
    <input bind:this={input} class="oc-field ai-pick__input" type="text" role="combobox" aria-label={label} aria-expanded={open} aria-haspopup="listbox"
        aria-controls={`${uid}-list`} aria-autocomplete="list" aria-activedescendant={open && isOption(active) ? idOf(active) : undefined}
        value={shownText} placeholder={loading ? t('settings.ai.picker.loading') : placeholder} {disabled} spellcheck="false" autocomplete="off"
        data-ai={`${dataAi}-input`} onfocus={show} onclick={show} oninput={onInput} onkeydown={onKey} />
    <span class="ai-pick__chev" aria-hidden="true"><Icon name="chevron-down" size={12} /></span>
    {#if open}
        <div class="ai-pick__panel popup-focus" class:ai-pick__panel--sheet={sheet} style={panelStyle} onmousedown={(e) => e.preventDefault()} role="presentation">
            <div class="ai-pick__list" id={`${uid}-list`} role="listbox" aria-label={label} bind:this={list}
                onscroll={(e) => (scrollTop = e.currentTarget.scrollTop)} data-count={optionCount} data-ai={`${dataAi}-list`}>
                <div class="ai-pick__space" style:height="{total}px">
                    {#each visible as { entry, index } (index)}
                        {#if entry.kind === 'header'}
                            <div class="ai-pick__head ai-pick__head--{entry.section}" role="presentation" style:top="{offsets[index]}px" style:height="{HEAD_H}px">{entry.title || t('settings.ai.picker.other')}</div>
                        {:else if entry.kind === 'custom'}
                            <!-- svelte-ignore a11y_click_events_have_key_events, a11y_interactive_supports_focus -->
                            <div class="ai-pick__opt ai-pick__opt--custom" class:ai-pick__opt--active={index === active} role="option" id={idOf(index)} aria-selected="false"
                                aria-posinset={posOf(index)} aria-setsize={optionCount} style:top="{offsets[index]}px" style:height="{ROW_H}px"
                                data-ai={`${dataAi}-custom`} onmouseenter={() => (active = index)} onclick={() => choose(index)}>
                                <span class="ai-pick__id">{t('settings.ai.picker.use', { id: entry.id })}</span>
                            </div>
                        {:else}
                            <!-- svelte-ignore a11y_click_events_have_key_events, a11y_interactive_supports_focus -->
                            <div class="ai-pick__opt" class:ai-pick__opt--active={index === active} class:ai-pick__opt--current={entry.item.id === value} role="option" id={idOf(index)}
                                aria-selected={entry.item.id === value} aria-posinset={posOf(index)} aria-setsize={optionCount} style:top="{offsets[index]}px"
                                style:height="{ROW_H}px" data-ai={`${dataAi}-option`} data-id={entry.item.id} onmouseenter={() => (active = index)} onclick={() => choose(index)}>
                                {#if entry.item.preset}<span class="ai-pick__opt-mark"><ProviderMark preset={entry.item.preset} size={16} /></span>{/if}
                                <span class="ai-pick__opt-body">
                                    <span class="ai-pick__id">{#each highlight(entry.item.text, terms) as run, r (r)}<span class:ai-pick__hit={run.hit}>{run.text}</span>{/each}</span>
                                    {#if entry.item.name || entry.item.detail}
                                        <span class="ai-pick__fact">{entry.item.detail}{entry.item.name && entry.item.detail ? ' · ' : ''}{#each highlight(entry.item.name, terms) as run, r (r)}<span class:ai-pick__hit={run.hit}>{run.text}</span>{/each}</span>
                                    {/if}
                                </span>
                                {#each entry.item.flags as flag (flag)}<span class="ai-pick__flag">{t(`settings.ai.picker.flag.${flag}`)}</span>{/each}
                            </div>
                        {/if}
                    {/each}
                </div>
            </div>
            {#if entries.length === 0}
                <p class="ai-pick__none" data-ai={`${dataAi}-none`}>{all.length === 0 ? t('settings.ai.picker.empty') : t('settings.ai.picker.no_match')}</p>
            {/if}
            <div class="ai-pick__foot" aria-hidden="true">{t('settings.ai.picker.count', { n: optionCount })}</div>
        </div>
    {/if}
</div>
