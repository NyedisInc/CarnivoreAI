<script lang="ts">
  import { onDestroy } from 'svelte';
  import Button from '../base/Button.svelte';
  import Checkbox from '../base/Checkbox.svelte';
  import Field from '../base/Field.svelte';
  import Segmented from '../base/Segmented.svelte';
  import { t } from '../i18n/index.svelte';
  import { terminalFont, type TerminalFontState } from './terminal-font';
  import { faceWeights, isMonospace, weightNumber, type InstalledFamily, type LocalFace } from './installed-fonts';

  const font = terminalFont();
  let size = $state(font ? font.size() : 14);
  let draft = $state(font ? font.family() : '');
  let weight = $state(font ? font.weight() : 'normal');
  let status = $state<'idle' | 'applying' | 'saved' | 'error'>('idle');
  let error = $state<string | null>(null);
  let installed = $state<InstalledFamily[]>([]);
  let open = $state(false);
  let showAll = $state(false);
  let listing = $state(false);
  let debounce: ReturnType<typeof setTimeout> | null = null;
  const canList = typeof (globalThis as { queryLocalFonts?: unknown }).queryLocalFonts === 'function';

  const stop = font?.onChange((next: TerminalFontState) => {
    size = next.size;
    weight = next.weight;
    if (!debounce && next.family !== draft && status !== 'applying') draft = next.family;
  });
  onDestroy(() => {
    stop?.();
    if (debounce) clearTimeout(debounce);
  });

  const preview = $derived(font ? font.familyStack(draft) : '');
  const previewWeight = $derived(font ? font.WEIGHTS[weight as keyof typeof font.WEIGHTS]?.fontWeight ?? 400 : 400);
  const weightOptions = $derived(['light', 'normal', 'medium', 'bold'].map((value) => ({ value, label: t(`terminal_font.weight.${value}`) })));
  const shown = $derived(showAll ? installed : installed.filter((f) => f.mono));
  const weightMissing = $derived.by(() => {
    const match = installed.find((f) => f.family.toLowerCase() === draft.trim().toLowerCase());
    return !!match && !match.weights.includes(weightNumber(weight));
  });

  async function saveFamily(): Promise<void> {
    if (!font) return;
    if (debounce) { clearTimeout(debounce); debounce = null; }
    status = 'applying';
    error = null;
    const ok = await font.setFamily(draft);
    if (ok) {
      draft = font.family();
      status = 'saved';
    } else {
      status = 'error';
      error = t('terminal_font.family_refused');
    }
  }

  function typed(): void {
    status = 'applying';
    if (debounce) clearTimeout(debounce);
    debounce = setTimeout(() => void saveFamily(), 400);
  }

  function pickWeight(value: string): void {
    if (!font) return;
    font.setWeight(value);
    weight = font.weight();
    status = 'saved';
    error = null;
  }

  function pick(name: string): void {
    draft = name;
    open = false;
    void saveFamily();
  }

  async function toggleList(): Promise<void> {
    if (open) { open = false; return; }
    open = true;
    if (installed.length || listing) return;
    const query = (globalThis as { queryLocalFonts?: () => Promise<LocalFace[]> }).queryLocalFonts;
    if (!query) return;
    listing = true;
    try {
      const faces = await query();
      const byFamily = new Map<string, LocalFace[]>();
      for (const face of faces) byFamily.set(face.family, [...(byFamily.get(face.family) ?? []), face]);
      installed = [...byFamily.entries()]
        .map(([family, list]) => ({ family, mono: isMonospace(family), weights: faceWeights(list) }))
        .sort((a, b) => Number(b.mono) - Number(a.mono) || a.family.localeCompare(b.family));
    } catch (err) {
      open = false;
      status = 'error';
      error = t('terminal_font.list_failed');
      console.warn('TerminalFontPanel: queryLocalFonts failed', err);
    } finally {
      listing = false;
    }
  }
</script>

<div class="terminal-font-panel" data-settings-section="terminal-font">
  {#if !font}
    <p class="settings-field-hint" role="status">{t('terminal_font.unavailable')}</p>
  {:else}
    <div class="terminal-font-panel__row">
      <span class="terminal-font-panel__label">{t('terminal_font.size')}</span>
      <Button size="sm" onclick={() => font.step(-1)} disabled={size <= font.MIN_SIZE} aria-label={t('terminal_font.smaller')} data-terminal-font="smaller">a-</Button>
      <output class="terminal-font-panel__value" data-terminal-font="size">{size}</output>
      <Button size="sm" onclick={() => font.step(1)} disabled={size >= font.MAX_SIZE} aria-label={t('terminal_font.bigger')} data-terminal-font="bigger">a+</Button>
      <Button size="sm" variant="quiet" onclick={() => font.reset()} disabled={size === font.DEFAULT_SIZE} data-terminal-font="reset">{t('terminal_font.reset')}</Button>
    </div>
    <div class="terminal-font-panel__row">
      <Field
        label={t('terminal_font.family')}
        bind:value={draft}
        placeholder={t('terminal_font.family_placeholder')}
        maxlength={200}
        oninput={typed}
        onchange={() => void saveFamily()}
        data-terminal-font="family"
      />
      {#if canList}
        <Button size="sm" onclick={() => void toggleList()} aria-expanded={open} data-terminal-font="list">{t('terminal_font.list_installed')}</Button>
      {/if}
    </div>
    {#if open}
      <div class="terminal-font-panel__list" role="listbox" aria-label={t('terminal_font.list_installed')} data-terminal-font="options">
        {#if listing}
          <p class="settings-field-hint" role="status">{t('terminal_font.listing')}</p>
        {:else}
          <div class="terminal-font-panel__filter">
            <Checkbox label={t('terminal_font.show_all')} bind:checked={showAll} />
          </div>
          {#each shown as f (f.family)}
            <button type="button" role="option" data-btn="row" aria-selected={f.family === draft} class="terminal-font-panel__option"
              style:font-family={`"${f.family}", monospace`} onclick={() => pick(f.family)} data-terminal-font-option={f.family}>{f.family}</button>
          {:else}
            <p class="settings-field-hint">{t('terminal_font.none_listed')}</p>
          {/each}
        {/if}
      </div>
    {/if}
    <div class="terminal-font-panel__row">
      <span class="terminal-font-panel__label">{t('terminal_font.weight')}</span>
      <Segmented label={t('terminal_font.weight')} options={weightOptions} value={weight} onchange={pickWeight} data-terminal-font="weight" />
    </div>
    {#if weightMissing}
      <p class="settings-field-hint" data-terminal-font="weight-missing">{t('terminal_font.weight_missing')}</p>
    {/if}
    <div class="terminal-font-panel__preview" style:font-family={preview} style:font-size={`${size}px`} style:font-weight={previewWeight} data-terminal-font="preview">
      ~/carnivore-projects main{''} {''} ❯ npm run build
    </div>
    <p class="terminal-font-panel__status" data-state={status} role="status" aria-live="polite" data-terminal-font="status">
      {#if status === 'applying'}{t('terminal_font.applying')}{:else if status === 'saved'}{t('terminal_font.saved')}{:else if status === 'error'}{error}{/if}
    </p>
  {/if}
</div>

<style>
  .terminal-font-panel {
    display: flex;
    flex-direction: column;
    gap: var(--oc-space-2);
  }
  .terminal-font-panel__row {
    display: flex;
    align-items: flex-end;
    gap: var(--oc-space-2);
    flex-wrap: wrap;
  }
  .terminal-font-panel__label {
    align-self: center;
    font-family: var(--font-mono);
    font-size: var(--oc-fs-label);
    letter-spacing: var(--oc-tracking-label);
    text-transform: uppercase;
    color: var(--oc-orange);
  }
  .terminal-font-panel__value {
    align-self: center;
    min-width: 2.5ch;
    text-align: center;
    font-family: var(--font-mono);
    color: var(--oc-text-primary);
  }
  .terminal-font-panel__preview {
    padding: var(--oc-space-2) var(--oc-space-3);
    box-shadow: inset 0 0 0 1px var(--oc-line-hairline);
    border-radius: 2px;
    color: var(--oc-text-primary);
    background: var(--oc-ground-field);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .terminal-font-panel__list {
    max-height: 14rem;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    padding: var(--oc-space-1);
    box-shadow: inset 0 0 0 1px var(--oc-line-hairline);
    border-radius: 2px;
    background: var(--oc-ground-field);
  }
  .terminal-font-panel__filter {
    padding: var(--oc-space-1) var(--oc-space-2);
  }
  .terminal-font-panel__option {
    justify-content: flex-start;
    text-align: left;
  }

  .terminal-font-panel__status {
    margin: 0;
    min-height: 1.2em;
    font-family: var(--font-mono);
    font-size: var(--oc-fs-label);
    color: var(--oc-text-muted);
  }
  .terminal-font-panel__status[data-state='saved'] {
    color: var(--oc-green);
  }
  .terminal-font-panel__status[data-state='error'] {
    color: var(--oc-coral);
  }
</style>
