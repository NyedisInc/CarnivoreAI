
<script lang="ts" module>
    let nextId = 0;
    export interface ChoiceItem { id: string; label: string; disabled?: boolean; hint?: string }
    export interface RowState { selected: boolean; active: boolean; inTrigger: boolean }
</script>

<script lang="ts" generics="T extends ChoiceItem">
    import type { Snippet } from 'svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import './dropdown.css';
    import { nextOption, typeahead } from './listbox-nav';
    import { isSheetWidth, placePanel } from './placement';

    interface Props {
        items: readonly T[];
        value?: string;
        onChange?: (id: string) => void;
        multiple?: boolean;
        values?: readonly string[];
        onToggle?: (id: string) => void;
        summary?: string;
        placeholder?: string;
        label: string;
        description?: string;
        disabled?: boolean;
        compact?: boolean;
        row: Snippet<[T, RowState]>;
        dataKey?: string;
        t?: Translate;
    }
    const { items, value = '', onChange = () => undefined, multiple = false, values = [], onToggle = () => undefined, summary = '', placeholder = '', label, description = '', disabled = false, compact = false, row, dataKey = 'choice', t = reactiveT }: Props = $props();

    const uid = `cdd-${(nextId += 1)}`;
    let open = $state(false);
    let active = $state(0);
    let panelStyle = $state('');
    let sheet = $state(false);
    let root: HTMLDivElement | undefined = $state();
    let typed = '';
    let typedAt = 0;

    const isChosen = (id: string): boolean => (multiple ? values.includes(id) : id === value);
    const selectedIndex = $derived(multiple ? items.findIndex((i) => values.includes(i.id)) : items.findIndex((i) => i.id === value));
    const selected = $derived(selectedIndex >= 0 ? items[selectedIndex] : undefined);
    const idOf = (index: number): string => `${uid}-o-${index}`;
    const step = (from: number, by: 1 | -1): number => nextOption(items, from, by, () => true);

    function place(): void {
        if (!root) return;
        const placed = placePanel(root.getBoundingClientRect(), { width: window.innerWidth, height: window.innerHeight }, isSheetWidth(), (w) => w);
        sheet = placed.sheet;
        panelStyle = placed.style;
    }

    function reveal(index: number): void {
        queueMicrotask(() => document.getElementById(idOf(index))?.scrollIntoView?.({ block: 'nearest' }));
    }

    function setActive(index: number): void {
        if (index < 0 || index >= items.length) return;
        active = index;
        reveal(index);
    }

    function show(at?: number): void {
        if (open || disabled || items.length === 0) return;
        open = true;
        place();
        setActive(at ?? (selectedIndex >= 0 ? selectedIndex : 0));
    }

    function hide(refocus = false): void {
        open = false;
        if (refocus) root?.querySelector<HTMLElement>('[role="combobox"]')?.focus();
    }

    function choose(index: number): void {
        const item = items[index];
        if (!item || item.disabled) return;
        if (multiple) {
            onToggle(item.id);
            return;
        }
        hide(true);
        if (item.id !== value) onChange(item.id);
    }

    function jump(key: string): number {
        const now = Date.now();
        typed = now - typedAt > 500 ? key : typed + key;
        typedAt = now;
        return typeahead(items.map((i) => i.label), open ? active : selectedIndex, typed);
    }

    function onKey(e: KeyboardEvent): void {
        if (disabled) return;
        const key = e.key;
        const printable = key.length === 1 && key !== ' ' && !e.ctrlKey && !e.metaKey && !e.altKey;
        if (!open) {
            if (key === 'ArrowDown' || key === 'ArrowUp' || key === 'Enter' || key === ' ') { e.preventDefault(); show(); }
            else if (key === 'Home') { e.preventDefault(); show(0); }
            else if (key === 'End') { e.preventDefault(); show(items.length - 1); }
            else if (printable) { const at = jump(key); if (at >= 0) { e.preventDefault(); show(at); } }
            return;
        }
        if (key === 'ArrowDown') { e.preventDefault(); const to = step(active + 1, 1); setActive(to >= 0 ? to : active); }
        else if (key === 'ArrowUp') { e.preventDefault(); const to = step(active - 1, -1); setActive(to >= 0 ? to : active); }
        else if (key === 'PageDown') { e.preventDefault(); setActive(Math.min(items.length - 1, active + 8)); }
        else if (key === 'PageUp') { e.preventDefault(); setActive(Math.max(0, active - 8)); }
        else if (key === 'Home') { e.preventDefault(); setActive(0); }
        else if (key === 'End') { e.preventDefault(); setActive(items.length - 1); }
        else if (key === 'Enter' || key === ' ') { e.preventDefault(); choose(active); }
        else if (key === 'Tab') hide();
        else if (printable) { const at = jump(key); if (at >= 0) setActive(at); }
    }

    function onFocusOut(e: FocusEvent): void {
        if (open && !root?.contains(e.relatedTarget as Node | null)) hide();
    }

    $effect(() => {
        if (!open) return;
        const again = (): void => place();
        const escape = (e: KeyboardEvent): void => {
            if (e.key !== 'Escape') return;
            e.preventDefault();
            e.stopPropagation();
            hide(true);
        };
        window.addEventListener('resize', again);
        window.addEventListener('scroll', again, true);
        window.addEventListener('animationend', again, true);
        window.addEventListener('keydown', escape, true);
        return () => {
            window.removeEventListener('resize', again);
            window.removeEventListener('scroll', again, true);
            window.removeEventListener('animationend', again, true);
            window.removeEventListener('keydown', escape, true);
        };
    });
</script>

<div class="cdd" class:cdd--open={open} class:cdd--compact={compact} bind:this={root} data-choice={dataKey} data-open={open} onfocusout={onFocusOut}>
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <div class="cdd__trigger oc-field oc-focus-host" role="combobox" tabindex={disabled ? -1 : 0} aria-haspopup="listbox" aria-expanded={open}
        aria-controls={`${uid}-list`} aria-label={label} aria-disabled={disabled ? 'true' : undefined}
        aria-activedescendant={open ? idOf(active) : undefined} data-choice-trigger onkeydown={onKey} onclick={() => (open ? hide() : show())}>
        <span class="cdd__row">{#if multiple}<span class="cdd__summary">{summary}</span>{:else if selected}{@render row(selected, { selected: true, active: false, inTrigger: true })}{:else if placeholder}<span class="cdd__summary">{placeholder}</span>{/if}</span>
        <span class="cdd__chev" aria-hidden="true"><Icon name="chevron-down" size={12} /></span>
    </div>
    {#if open}
        <div class="cdd__panel popup-focus" class:cdd__panel--sheet={sheet} style={panelStyle} onmousedown={(e) => e.preventDefault()} role="presentation">
            <div class="cdd__list" id={`${uid}-list`} role="listbox" aria-multiselectable={multiple ? 'true' : undefined} aria-label={label} aria-describedby={description ? `${uid}-desc` : undefined} data-choice-list>
                {#if description}<span class="cdd__sr" id={`${uid}-desc`}>{description}</span>{/if}
                {#each items as item, i (item.id)}
                    <!-- svelte-ignore a11y_click_events_have_key_events, a11y_interactive_supports_focus -->
                    <div class="cdd__opt" class:cdd__opt--active={i === active} class:cdd__opt--selected={isChosen(item.id)} class:cdd__opt--refused={item.disabled}
                        role="option" id={idOf(i)} aria-selected={isChosen(item.id)} aria-disabled={item.disabled ? 'true' : undefined}
                        aria-posinset={i + 1} aria-setsize={items.length} aria-describedby={item.hint ? `${idOf(i)}-hint` : undefined}
                        data-choice-option={item.id} onmouseenter={() => (active = i)} onclick={() => choose(i)}>
                        {@render row(item, { selected: isChosen(item.id), active: i === active, inTrigger: false })}
                        {#if item.disabled}<span class="cdd__sr">{t('launch_picker.dropdown.unavailable')}</span>{/if}
                        {#if item.hint}<span class="cdd__sr" id={`${idOf(i)}-hint`}>{item.hint}</span>{/if}
                    </div>
                {/each}
            </div>
        </div>
    {/if}
</div>
