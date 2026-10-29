<script lang="ts">
  /* the bottom bar the terminal grid */
  import { t } from '../sdk';
  import { Icon, buttonAttrs } from '../sdk/ui';
  import '../sdk/host-chrome';

  interface Props {
    edge: 'side' | 'bottom';
    keys: readonly string[];
    lit?: string | null;
    litTone?: string | null;
    litLabel?: string;
    onlitmenu?: (key: DOMRect) => void;
  }

  const { edge, keys, lit = null, litTone = null, litLabel = '', onlitmenu }: Props = $props();

  function onContext(event: MouseEvent): void {
    event.preventDefault();
    onlitmenu?.((event.currentTarget as HTMLElement).getBoundingClientRect());
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key !== 'ContextMenu' && !(event.key === 'F10' && event.shiftKey)) return;
    event.preventDefault();
    onlitmenu?.((event.currentTarget as HTMLElement).getBoundingClientRect());
  }
</script>

<nav class="rail dwl-chrome-bar dwl-chrome-bar--{edge}" class:rail--bottom={edge === 'bottom'} style="--rail-h: 36px; --rail-track: 36px;" data-bar={edge}
  aria-label={t('cplug.devwidgetlab.chrome.bar')} inert={!lit}>
  <div class="rail__layer" data-out="true">
    {#each keys as name (name)}
      <button type="button" class="dwl-chrome-key" {...buttonAttrs('quiet', 'icon')} tabindex="-1" inert aria-label={t(`cplug.devwidgetlab.chrome.key.${name}`)}><Icon {name} size={16} /></button>
    {/each}
    {#if lit}
      <button type="button" class="dwl-chrome-key" {...buttonAttrs('quiet', 'icon')} aria-pressed="true" aria-haspopup="menu" aria-label={litLabel} data-key-open data-icon={lit} style={litTone ? `--rail-tone: var(--${litTone})` : undefined} oncontextmenu={onContext} onkeydown={onKey}><Icon name={lit} size={16} /></button>
    {/if}
    {#if edge === 'bottom'}
      <span class="dwl-chrome-bar-end"><button type="button" class="dwl-chrome-key" {...buttonAttrs('quiet', 'icon')} tabindex="-1" inert aria-label={t('cplug.devwidgetlab.chrome.key.bell')}><Icon name="bell" size={16} /></button></span>
    {/if}
  </div>
</nav>
