<script lang="ts">
  /* the drawer has focus */
  import Icon from '../../opscenter/ui/Icon.svelte';
  import Button from '../base/Button.svelte';
  import Field from '../base/Field.svelte';
  import { t } from '../i18n/index.svelte';
  import { readChoice, readFlag, writeChoice } from '../ui/prefs.svelte';
  import { untrack } from 'svelte';
  import CascadeMenu from './CascadeMenu.svelte';
  import { closing } from '../widget-menu/model';
  import SearchTerms from './SearchTerms.svelte';
  import { forwardMenuKey } from '../item-menu/page-row';
  import { contextProvider } from '../deepsearch/providers';
  import { cursorTarget, moveCursor, resetCursor, searchD } from '../drawer/search-d.svelte';
  import { DeepSearchController, SUGGEST_LIST_ID } from '../deepsearch/deepsearch.svelte';
  import { SEARCH_AGENTS_BAND } from '../sidebar-shell/search-plan';
  import { rowEls, setFocusRow } from '../sidebar-shell/row-focus';
  import type { MenuNode } from './add-component-menu';
  import {
    DRAWER_DEEP_ACTIVE_CLASS,
    DRAWER_DEEP_SEARCH_KEY,
    DRAWER_SEARCH_ID,
    DRAWER_SEARCH_MODE_KEY,
  } from './drawer-tabs';
  import { CONTEXT_MODE_ID, LEGACY_GREP_MODE, MODE_ALL, activeMode, availableModes, knownModeIds, type SearchModeDef } from './search-modes';

  interface Props {
    modes?: SearchModeDef[];
  }
  let { modes: givenModes }: Props = $props();

  interface SearchGlobal {
    setQuery?: (raw: string) => void;
  }

  function searchApi(): SearchGlobal | null {
    return (globalThis as { SessionSidebarSearch?: SearchGlobal }).SessionSidebarSearch ?? null;
  }

  let value = $state('');
  let inputEl = $state<HTMLInputElement | null>(null);
  const modes = $derived(givenModes ?? availableModes());
  function rememberedMode(): string {
    const ids = givenModes ? givenModes.map((m) => m.id) : knownModeIds();
    const stored = readChoice<string>(DRAWER_SEARCH_MODE_KEY, ids, '');
    return stored !== '' ? stored : readFlag(DRAWER_DEEP_SEARCH_KEY) ? LEGACY_GREP_MODE : '';
  }
  let chosen = $state(rememberedMode());
  const mode = $derived(activeMode(modes, chosen));
  const provider = $derived(mode.provider);
  const deep = $derived(provider !== null);
  const controller = $derived.by(() => {
    const made = (provider ? provider.create() : contextProvider().create()) as DeepSearchController;
    made.showActions = mode.id === CONTEXT_MODE_ID;
    return made;
  });
  let modeOpen = $state(false);
  let modeButton = $state<HTMLElement | null>(null);
  let zone = $state<'box' | 'terms' | 'results'>('box');

  const modeRoot = $derived<MenuNode[]>(
    closing(
      modes.map((m) => ({
        id: m.id,
        label: t(m.nameKey),
        icon: m.icon,
        checked: m.id === mode.id,
        run: () => chooseMode(m.id),
      })),
      () => (modeOpen = false),
    ),
  );

  const showDeep = $derived(deep && value.trim() !== '');
  const listing = $derived(!deep && value.trim() !== '');
  const combined = $derived(mode.id === MODE_ALL);
  const hasHits = $derived(showDeep && controller.hasHits);
  const suggesting = $derived(mode.id === CONTEXT_MODE_ID && value.trim() !== '' && controller.suggesting === true);
  const activeDescendant = $derived.by(() => {
    if (suggesting && zone === 'terms' && controller.suggestActiveId) return controller.suggestActiveId;
    if (hasHits && provider) return `${provider.hitIdPrefix}${controller.active}`;
    return undefined;
  });

  $effect(() => {
    const panel = document.getElementById('session-sidebar-panel');
    panel?.classList.toggle(DRAWER_DEEP_ACTIVE_CLASS, showDeep);
    return () => panel?.classList.remove(DRAWER_DEEP_ACTIVE_CLASS);
  });

  $effect(() => {
    const current = controller;
    return () => current.cancel();
  });

  $effect(() => {
    searchD.controller = listing && combined ? controller : null;
    return () => {
      searchD.controller = null;
    };
  });

  $effect(() => {
    searchD.actions = {
      searchConversations: () => chooseMode(CONTEXT_MODE_ID),
      clear: () => clear(true),
    };
    return () => {
      searchD.actions = null;
    };
  });

  $effect(() => {
    void controller;
    untrack(() => apply(value));
  });

  $effect(() => {
    const current = controller;
    current.onReplaceQuery = (text: string) => {
      apply(text);
      inputEl?.focus();
    };
    return () => {
      current.onReplaceQuery = undefined;
    };
  });

  $effect(() => {
    if (!suggesting && zone === 'terms') zone = 'box';
  });

  function apply(next: string): void {
    value = next;
    searchApi()?.setQuery?.(deep ? '' : next);
    controller.query = next;
    controller.onType();
    zone = 'box';
    resetCursor();
  }

  function chooseMode(id: string): void {
    chosen = id;
    writeChoice(DRAWER_SEARCH_MODE_KEY, id);
    modeButton?.focus();
  }

  function onInput(event: Event & { currentTarget: HTMLInputElement }): void {
    apply(event.currentTarget.value);
  }

  function clear(refocus: boolean): void {
    apply('');
    if (refocus) inputEl?.focus();
  }

  function focusFirstRow(): void {
    const first = rowEls()[0];
    if (!first) return;
    setFocusRow(first.dataset.name ?? null, first.dataset.band ?? null, true);
  }

  function walk(delta: number): void {
    if (listing) moveCursor(delta);
    else if (hasHits) controller.move(delta);
  }

  function openCursor(event: KeyboardEvent): boolean {
    const target = cursorTarget();
    if (!target) return false;
    if (target.kind === 'agent') {
      if (event.metaKey || event.ctrlKey) return false;
      const list = document.getElementById('session-sidebar-list');
      const row = [...(list?.querySelectorAll<HTMLElement>('.session-sidebar-row') ?? [])]
        .find((el) => el.dataset.name === target.name && el.dataset.band === SEARCH_AGENTS_BAND);
      row?.click();
      return row !== undefined;
    }
    const name = DeepSearchController.nameOf(target.top.group);
    if (event.metaKey || event.ctrlKey) void controller.go(target.top.group);
    else void controller.pickHit(target.top.group, target.top.hit, name);
    return true;
  }

  function onKeydown(event: KeyboardEvent): void {
    const key = event.key;
    if (suggesting && zone === 'terms') {
      if (key === 'ArrowLeft' || key === 'ArrowRight') {
        event.preventDefault();
        controller.suggestMove(key === 'ArrowRight' ? 1 : -1);
        return;
      }
      if (key === 'Enter' && controller.suggestPick()) {
        event.preventDefault();
        event.stopPropagation();
        zone = 'box';
        return;
      }
      if (key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        controller.suggestActive = -1;
        zone = 'box';
        return;
      }
      if (key === 'ArrowDown') {
        event.preventDefault();
        controller.suggestActive = -1;
        zone = listing || hasHits ? 'results' : 'box';
        return;
      }
      if (key === 'ArrowUp') {
        event.preventDefault();
        controller.suggestActive = -1;
        zone = 'box';
        return;
      }
    }
    if (hasHits && provider && forwardMenuKey(event, document.getElementById(`${provider.hitIdPrefix}${controller.active}`))) return;
    if (key === 'ArrowUp' && zone === 'results' && suggesting && (listing ? searchD.cursor === 0 : controller.active === 0)) {
      event.preventDefault();
      controller.suggestActive = 0;
      zone = 'terms';
      return;
    }
    if (key === 'Escape' && value !== '') {
      event.preventDefault();
      event.stopPropagation();
      clear(true);
    } else if (key === 'ArrowDown' && suggesting && zone === 'box') {
      event.preventDefault();
      controller.suggestActive = 0;
      zone = 'terms';
    } else if ((key === 'ArrowDown' || key === 'ArrowUp') && (listing || hasHits)) {
      event.preventDefault();
      zone = 'results';
      walk(key === 'ArrowDown' ? 1 : -1);
    } else if (key === 'Enter' && hasHits && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      event.stopPropagation();
      void controller.goActive?.();
    } else if (key === 'Enter' && hasHits) {
      event.preventDefault();
      event.stopPropagation();
      void controller.pickActive();
    } else if (key === 'Enter' && listing && openCursor(event)) {
      event.preventDefault();
      event.stopPropagation();
    } else if (key === 'ArrowDown' && !showDeep) {
      event.preventDefault();
      focusFirstRow();
    }
  }

  function onGlobalKeydown(event: KeyboardEvent): void {
    if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return;
    const panel = document.getElementById('session-sidebar-panel');
    const container = document.getElementById(DRAWER_SEARCH_ID);
    if (!panel || !container || container.hidden) return;
    const active = document.activeElement as HTMLElement | null;
    const tag = active?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || active?.isContentEditable) return;
    event.preventDefault();
    inputEl?.focus();
  }
</script>

<svelte:window onkeydown={onGlobalKeydown} />

<div class="ds" class:ds--deep={showDeep}>
  <div class="ds-row">
    <Field
      variant="search"
      id="ds-search-input"
      label={deep && provider ? t(provider.labelKey) : t('drawer.search.label')}
      bind:value
      bind:input={inputEl}
      clearLabel={t('drawer.search.clear')}
      onclear={() => apply('')}
      hint={t('drawer.search.hint.focus')}
      hintFilled={t('drawer.search.hint.clear')}
      placeholder={deep && provider ? t(provider.placeholderKey) : t('drawer.search.placeholder')}
      autocomplete="off"
      spellcheck={false}
      role={value.trim() !== '' ? 'combobox' : undefined}
      aria-expanded={value.trim() !== '' ? hasHits || suggesting || listing : undefined}
      aria-controls={suggesting ? SUGGEST_LIST_ID : deep && provider ? provider.resultsId : undefined}
      aria-activedescendant={activeDescendant}
      aria-autocomplete={value.trim() !== '' ? 'list' : undefined}
      oninput={onInput}
      onkeydown={onKeydown}
    >
      {#snippet trailing()}
        
        <Button
          variant="quiet"
          size="sm"
          data-ds-mode
          bind:element={modeButton}
          aria-haspopup="menu"
          aria-expanded={modeOpen}
          aria-label={t('drawer.search.mode.button', { mode: t(mode.nameKey) })}
          data-mode={mode.id}
          onclick={() => (modeOpen = !modeOpen)}
        >
          <Icon name={mode.icon} size={16} />
          <span class="ds-mode-arrow"><Icon name="chevron-down" size={10} /></span>
        </Button>
      {/snippet}
    </Field>
    {#if suggesting}<SearchTerms {controller} active={zone === 'terms'} />{/if}
  </div>
  {#if showDeep && provider}
    <provider.Results {controller} />
  {/if}
</div>

{#if modeOpen}
  <CascadeMenu root={modeRoot} anchor={modeButton} label={t('drawer.search.mode.menu')} alignEnd onClose={() => (modeOpen = false)} />
{/if}

<style>
  @layer components {
    .ds {
      display: flex;
      flex-direction: column;
    }

    .ds--deep {
      flex: 1 1 auto;
      min-height: 0;
    }

    :global(#session-sidebar-panel.drawer-deep-search #session-sidebar-search:not([hidden])) {
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      min-height: 0;
    }

    :global(#session-sidebar-panel.drawer-deep-search #session-sidebar-list) {
      display: none;
    }

    .ds-row {
      display: flex;
      flex-direction: column;
      padding: var(--oc-space-1) var(--oc-space-2);
      background: var(--oc-ground-chrome);
      border-bottom: var(--oc-border) solid var(--oc-line-panel);
    }

    .ds-row :global(.oc-search) {
      --oc-search-h: var(--drawer-field-h, var(--oc-control-h-sm));
    }

    :global([data-ds-mode]) {
      min-height: auto;
      line-height: inherit;
      transition: initial;
      display: inline-flex;
      align-items: center;
      flex: 0 0 auto;
      gap: var(--oc-space-1);
      height: 100%;
      padding: 0 var(--oc-space-2);
      border: 0;
      border-left: 1px solid var(--oc-line-rule);
      border-radius: 0 var(--oc-radius) var(--oc-radius) 0;
      background: transparent;
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      text-transform: lowercase;
      white-space: nowrap;
      cursor: pointer;
    }
    :global([data-ds-mode]:hover) {
      color: var(--oc-text-primary);
    }
    :global([data-ds-mode][aria-expanded='true']) {
      color: var(--oc-orange);
    }
    .ds-mode-arrow {
      display: inline-flex;
      color: var(--oc-text-muted);
    }
    @media (max-width: 1023px) {
      :global([data-ds-mode]) {
        position: relative;
      }
      :global([data-ds-mode]::after) {
        content: '';
        position: absolute;
        top: 50%;
        left: 0;
        right: 0;
        height: var(--oc-tap, 44px);
        transform: translateY(-50%);
      }
    }
  }
</style>
