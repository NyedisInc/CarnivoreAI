<script lang="ts">
  import { guideThemes, onGuideTheme, paintScope, type GuideTheme } from '../theme-scope';

  const SURFACES: readonly { token: string; label: string }[] = [
    { token: '--oc-surface-sunken', label: 'sunken' },
    { token: '--oc-surface-base', label: 'base' },
    { token: '--oc-surface-band', label: 'band' },
    { token: '--oc-surface-raised', label: 'raised' },
    { token: '--oc-surface-overlay', label: 'overlay' },
  ];

  let themes = $state<GuideTheme[]>([]);

  $effect(() => onGuideTheme(() => (themes = guideThemes())));

  function scoped(theme: GuideTheme) {
    return (el: HTMLElement): void => paintScope(el, theme, themes);
  }
</script>

{#if themes.length === 0}
  <p class="sg-caption">waiting for the theme list</p>
{:else}
  <div class="sg-bt-list">
    {#each themes as theme (theme.id)}
      <div class="sg-bt-strip" {@attach scoped(theme)}>
        <span class="sg-bt-name">{theme.name}</span>
        <div class="sg-bt-surfaces">
          {#each SURFACES as s (s.token)}
            <span class="sg-bt-surface" style:background={`var(${s.token})`}>
              <span class="sg-bt-ink">{s.label}</span>
              <span class="sg-bt-muted">muted</span>
            </span>
          {/each}
        </div>
        <div class="sg-bt-controls">
          <button type="button" class="oc-btn oc-btn--sm">cancel</button>
          <button type="button" class="oc-btn oc-btn--sm oc-btn--confirm">save</button>
          <button type="button" class="oc-btn oc-btn--sm oc-btn--danger">remove</button>
          <input class="oc-field sg-bt-field" type="text" value="field" aria-label={`field, ${theme.name}`} />
          <button type="button" class="oc-check" role="checkbox" aria-checked="true"><span class="oc-check__box"></span>on</button>
          <button type="button" class="oc-chip" aria-pressed="true">chip</button>
          <span class="sg-bt-control-line" title="--oc-line-control">control line</span>
        </div>
      </div>
    {/each}
  </div>
{/if}
