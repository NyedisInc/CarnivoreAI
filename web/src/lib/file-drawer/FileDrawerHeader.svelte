<script lang="ts">
  /* The file drawer's */
  import { untrack } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { Checkbox, IconButton } from '../base';
  import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
  import { filesRootPrefs, publishRootPrefs, writeRootPrefs, type TopFolder } from './roots-prefs.svelte';
  import {
    readDrawerPrefs,
    writeDrawerPref,
    type DrawerPrefs,
    type IgnoreStatus,
  } from './drawer-prefs';

  let {
    onQuery,
    onPrefs,
    onRefresh,
    onCollapseAll,
    onNewFile,
    onClose,
    onComponent,
    onSubmit,
    onScopeUp,
    onScopeClear,
  }: {
    onQuery: (query: string) => void;
    onPrefs: (prefs: DrawerPrefs) => void;
    onRefresh: () => void;
    onCollapseAll: () => void;
    onNewFile: () => void;
    onClose: () => void;
    onComponent?: () => void;
    onSubmit?: () => void;
    onScopeUp?: () => void;
    onScopeClear?: () => void;
  } = $props();

  let componentShown = $state(false);

  const DEBOUNCE_MS = 120;

  let text = $state('');
  let scopeLabel = $state('');
  let options = $state<DrawerPrefs>(readDrawerPrefs());
  let ignoreStatus = $state<IgnoreStatus>('unknown');
  let menuOpen = $state(false);
  let menuButton = $state<HTMLElement | null>(null);
  let menu = $state<HTMLElement | null>(null);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let sent = '';

  const ignoreUnavailable = $derived(ignoreStatus === 'unavailable');

  const rootPrefs = $derived(filesRootPrefs());
  let rootsFailed = $state(false);

  $effect(() => {
    const next = rootPrefs;
    if (publishRootPrefs(next)) untrack(() => onPrefs({ ...options }));
  });

  /* the settings overlay */
  async function setRoots(change: { showGlobalFolder?: boolean; topFolder?: TopFolder }): Promise<void> {
    rootsFailed = false;
    try {
      await writeRootPrefs(change);
    } catch {
      rootsFailed = true;
    }
  }

  function send(next: string): void {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    if (next === sent) return;
    sent = next;
    onQuery(next);
  }

  function onInput(): void {
    if (timer) clearTimeout(timer);
    const next = text;
    timer = setTimeout(() => send(next), DEBOUNCE_MS);
  }

  function onFieldKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape' && text) {
      event.preventDefault();
      event.stopPropagation();
      clearQuery();
    } else if (event.key === 'Escape' && scopeLabel) {
      event.preventDefault();
      event.stopPropagation();
      onScopeClear?.();
    } else if (event.key === 'Backspace' && !text && scopeLabel) {
      event.preventDefault();
      onScopeUp?.();
    } else if (event.key === 'Enter') {
      send(text);
      if (text) onSubmit?.();
    }
  }

  function toggle(which: keyof DrawerPrefs): void {
    options = { ...options, [which]: !options[which] };
    writeDrawerPref(which, options[which]);
    onPrefs({ ...options });
  }

  function toggleMenu(): void {
    menuOpen = !menuOpen;
  }

  export function prefs(): DrawerPrefs {
    return { ...options };
  }

  export function query(): string {
    return sent;
  }

  export function clearQuery(): void {
    text = '';
    send('');
  }

  export function setScope(label: string): void {
    scopeLabel = label;
  }

  export function setComponentShown(shown: boolean): void {
    componentShown = shown && !!onComponent;
  }

  export function setIgnoreStatus(status: IgnoreStatus): void {
    ignoreStatus = status;
  }

  export function escape(): boolean {
    if (menuOpen) {
      menuOpen = false;
      menuButton?.focus();
      return true;
    }
    if (text || sent) {
      clearQuery();
      return true;
    }
    if (scopeLabel) {
      onScopeClear?.();
      return true;
    }
    return false;
  }
</script>

<div class="fdh">
  <div class="fdh-row">
    <IconButton variant="quiet" id="config-editor-new" label={t('files.drawer.new_file')} onclick={() => onNewFile()}>
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10" /></svg>
    </IconButton>
    <span class="fdh-spacer"></span>
    <IconButton variant="quiet" data-action="collapse-all" label={t('files.drawer.collapse_all')} onclick={() => onCollapseAll()}>
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3.5h8M5 8h8M5 12.5h8M2.5 3.5h.01M2.5 8h.01M2.5 12.5h.01" /></svg>
    </IconButton>
    <IconButton variant="quiet" data-action="refresh" label={t('files.drawer.refresh')} onclick={() => onRefresh()}>
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13 8a5 5 0 1 1-1.5-3.55M13 2.5v2.5h-2.5" /></svg>
    </IconButton>
    <div class="fdh-menu-anchor">
      <IconButton variant="quiet" data-action="options" bind:element={menuButton}
        label={t('files.drawer.options')}
        aria-haspopup="dialog" aria-expanded={menuOpen} onclick={toggleMenu}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8h.01M8 8h.01M12.5 8h.01" class="fdh-dots" /></svg>
      </IconButton>
      {#if menuOpen}
        <AnchoredPopup class="fdh-menu" label={t('files.drawer.options')} anchor={menuButton} initialFocus="input:not(:disabled)" outside="capture"
          bind:element={menu} onClose={() => (menuOpen = false)}>
          <Checkbox data-pref="hideDot" checked={options.hideDot} label={t('files.drawer.hide_dot')}
            onchange={() => toggle('hideDot')} />
          <Checkbox data-pref="hideIgnored" checked={options.hideIgnored} label={t('files.drawer.hide_ignored')}
            disabled={ignoreUnavailable} onchange={() => toggle('hideIgnored')} />
          <div class="fdh-rule" role="separator"></div>
          <Checkbox data-pref="showGlobalFolder" checked={rootPrefs.showGlobal} label={t('files.drawer.show_global')}
            onchange={(event) => void setRoots({ showGlobalFolder: event.currentTarget.checked })} />
          <Checkbox data-pref="projectOnTop" checked={rootPrefs.topFolder === 'project'} label={t('files.drawer.project_on_top')}
            disabled={!rootPrefs.showGlobal}
            onchange={(event) => void setRoots({ topFolder: event.currentTarget.checked ? 'project' : 'global' })} />
          {#if rootsFailed}<p class="fdh-note" role="alert">{t('files.drawer.roots_failed')}</p>{/if}
        </AnchoredPopup>
      {/if}
    </div>
    {#if componentShown}
      <IconButton variant="quiet" data-action="as-component" label={t('files.drawer.as_component')} onclick={() => onComponent?.()}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 2.5h11v11h-11zM2.5 6h11M6 6v7.5" /></svg>
      </IconButton>
    {/if}
    <IconButton variant="close" id="config-editor-close" label={t('files.drawer.close')} onclick={() => onClose()}>
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" /></svg>
    </IconButton>
  </div>
<label class="fdh-find oc-focus-host">
    <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 4h11M4.5 8h7M6.5 12h3" /></svg>
    {#if scopeLabel}<span class="fdh-scope" data-role="find-scope">{scopeLabel}</span>{/if}
    <input type="search" class="fdh-input" data-role="find-files" data-base-exempt="the find box shares one frame with the scope crumb; the base search Field has no leading slot yet" autocomplete="off" spellcheck="false"
      placeholder={t('files.drawer.find')} aria-label={t('files.drawer.find_label')}
      bind:value={text} oninput={onInput} onkeydown={onFieldKeydown} />
  </label>
</div>

<style>
  .fdh {
    display: flex;
    flex-direction: column;
    gap: 6px;
    width: 100%;
    padding: 6px 8px 8px;
    box-sizing: border-box;
  }

  .fdh-row {
    display: flex;
    align-items: center;
    gap: 2px;
    --oc-ibtn-size: 24px;
  }

  .fdh-spacer {
    flex: 1 1 auto;
  }

  svg {
    width: 14px;
    height: 14px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.4;
    stroke-linecap: round;
    stroke-linejoin: round;
    flex-shrink: 0;
  }

  .fdh-dots {
    stroke-width: 2.2;
  }

  .fdh-menu-anchor {
    position: relative;
  }

  :global(.fdh-menu) {
    display: flex;
    flex-direction: column;
    min-width: 190px;
    padding: 4px;
  }

  .fdh-rule {
    height: 1px;
    margin: 4px 0;
    background: var(--oc-line-rule);
  }

  .fdh-note {
    margin: 0;
    padding: 4px 6px;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--oc-coral);
  }

  .fdh-find {
    display: flex;
    align-items: center;
    gap: 6px;
    height: 24px;
    padding: 0 8px;
    box-sizing: border-box;
    background: var(--oc-ground-field);
    border: 1px solid var(--oc-line-rule);
    border-radius: var(--oc-radius-sm, 2px);
    color: var(--oc-text-muted);
  }

  .fdh-find:focus-within {
    border-color: var(--oc-orange-dim);
  }

  .fdh-scope {
    flex: 0 1 auto;
    max-width: 55%;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    direction: rtl;
    unicode-bidi: plaintext;
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--oc-text-dim);
  }

  .fdh-input {
    flex: 1 1 auto;
    min-width: 0;
    height: 22px;
    padding: 0;
    border: none;
    outline: none;
    background: transparent;
    color: var(--oc-text-primary);
    font-family: var(--font-mono);
    font-size: 12px;
  }

  .fdh-input::placeholder {
    color: var(--oc-text-dim);
  }

  .fdh-input::-webkit-search-cancel-button {
    display: none;
  }
</style>
