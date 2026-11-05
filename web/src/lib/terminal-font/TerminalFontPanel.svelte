<script lang="ts">
  import { onDestroy } from 'svelte';
  import Button from '../base/Button.svelte';
  import Field from '../base/Field.svelte';
  import { t } from '../i18n/index.svelte';
  import { terminalFont, type TerminalFontState } from './terminal-font';

  const font = terminalFont();
  let size = $state(font ? font.size() : 14);
  let draft = $state(font ? font.family() : '');
  let error = $state<string | null>(null);
  let installed = $state<string[]>([]);
  const canList = typeof (globalThis as { queryLocalFonts?: unknown }).queryLocalFonts === 'function';

  const stop = font?.onChange((next: TerminalFontState) => {
    size = next.size;
    draft = next.family;
  });
  onDestroy(() => stop?.());

  const preview = $derived(font ? font.familyStack(draft) : '');

  async function saveFamily(): Promise<void> {
    if (!font) return;
    const ok = await font.setFamily(draft);
    error = ok ? null : t('terminal_font.family_refused');
    if (ok) draft = font.family();
  }

  async function listInstalled(): Promise<void> {
    const query = (globalThis as { queryLocalFonts?: () => Promise<{ family: string }[]> }).queryLocalFonts;
    if (!query) return;
    try {
      const faces = await query();
      installed = [...new Set(faces.map((f) => f.family))].sort((a, b) => a.localeCompare(b));
    } catch (err) {
      error = t('terminal_font.list_failed');
      console.warn('TerminalFontPanel: queryLocalFonts failed', err);
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
        list="terminal-font-installed"
        onchange={() => void saveFamily()}
        data-terminal-font="family"
      />
      {#if canList}
        <Button size="sm" onclick={() => void listInstalled()} data-terminal-font="list">{t('terminal_font.list_installed')}</Button>
      {/if}
      <datalist id="terminal-font-installed">
        {#each installed as name (name)}<option value={name}></option>{/each}
      </datalist>
    </div>
    <div class="terminal-font-panel__preview" style:font-family={preview} style:font-size={`${size}px`} data-terminal-font="preview">
      ~/carnivore-projects main{''} {''} ❯ npm run build
    </div>
    {#if error}
      <p class="settings-field-hint terminal-font-panel__error" role="alert">{error}</p>
    {/if}
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
  .terminal-font-panel__error {
    color: var(--oc-coral);
  }
</style>
