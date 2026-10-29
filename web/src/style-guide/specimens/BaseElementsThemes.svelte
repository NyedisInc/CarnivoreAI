<script lang="ts">
  import BaseElements from './BaseElements.svelte';
  import { guideThemes, onGuideTheme, paintScope, type GuideTheme } from '../theme-scope';

  let themes = $state<GuideTheme[]>([]);

  $effect(() => onGuideTheme(() => (themes = guideThemes())));

  function scoped(theme: GuideTheme) {
    return (el: HTMLElement): void => paintScope(el, theme, themes);
  }
</script>

{#if themes.length === 0}
  <p class="sg-caption">waiting for the theme list</p>
{:else}
  <div class="sg-bct sg-bet">
    {#each themes as theme (theme.id)}
      <div class="sg-bct__tile" data-theme-tile={theme.id} {@attach scoped(theme)}>
        <span class="sg-bc__label">{theme.name}</span>
        <BaseElements />
      </div>
    {/each}
  </div>
{/if}
