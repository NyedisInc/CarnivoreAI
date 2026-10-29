<script lang="ts">
  import Button from '../../lib/base/Button.svelte';
  import BaseElements from './BaseElements.svelte';
  import QuestionCardDemo from './QuestionCardDemo.svelte';
  import QuestionCardToday from './QuestionCardToday.svelte';
  import ShellsReview from './ShellsReview.svelte';
  import { guideThemes, onGuideTheme, paintScope, type GuideTheme } from '../theme-scope';

  const uid = $props.id();
  const pickerId = `sg-review-theme-${uid}`;
  let themes = $state<GuideTheme[]>([]);
  let picked = $state('');
  let panel = $state<HTMLElement>();

  $effect(() => onGuideTheme((id) => {
    themes = guideThemes();
    if (!picked) picked = id;
  }));

  $effect(() => {
    const theme = themes.find((t) => t.id === picked);
    if (panel && theme) paintScope(panel, theme, themes);
  });
</script>

<div class="sg-review" data-oc-base>
  <div class="sg-review__bar">
    <label for={pickerId}>theme for this panel</label>
    <select id={pickerId} bind:value={picked} data-review-theme>
      {#each themes as theme (theme.id)}<option value={theme.id}>{theme.name}</option>{/each}
    </select>
  </div>
  <div class="sg-review__panel" bind:this={panel} data-review-panel>
    <div class="sg-bc__group">
      <span class="sg-bc__label">base elements: plain html, no class</span>
      <BaseElements />
    </div>
    <div class="sg-bc__group">
      <span class="sg-bc__label">buttons: one component, a variant and a size</span>
      <div class="sg-be__row">
        <Button>secondary</Button>
        <Button variant="confirm">confirm</Button>
        <Button variant="danger">remove</Button>
        <Button variant="quiet">quiet</Button>
        <Button disabled>disabled</Button>
        <Button href="#review">a link</Button>
      </div>
      <div class="sg-be__row">
        <Button size="sm">secondary</Button>
        <Button size="sm" variant="confirm">confirm</Button>
        <Button size="sm" variant="danger">remove</Button>
        <Button size="sm" variant="quiet">quiet</Button>
        <Button size="sm" disabled>disabled</Button>
      </div>
      <div class="sg-be__row" data-review-pair>
        <Button size="sm">take recommendation</Button>
        <Button size="sm">add a note</Button>
      </div>
    </div>
    <div class="sg-bc__group">
      <span class="sg-bc__label">the task manager question card: today, and rebuilt from the base</span>
      <div class="sg-qc-compare">
        <div class="sg-qc-col"><span class="sg-bc__label">today (static copy)</span><QuestionCardToday /></div>
        <div class="sg-qc-col" data-review-card><span class="sg-bc__label">rebuilt</span><QuestionCardDemo /></div>
      </div>
    </div>
    <ShellsReview />
  </div>
</div>
