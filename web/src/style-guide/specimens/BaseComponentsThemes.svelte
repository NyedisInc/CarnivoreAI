<script lang="ts">
  import Button from '../../lib/base/Button.svelte';
  import Card from '../../lib/base/Card.svelte';
  import Field from '../../lib/base/Field.svelte';
  import List from '../../lib/base/List.svelte';
  import ListRow from '../../lib/base/ListRow.svelte';
  import State from '../../lib/base/State.svelte';
  import OptionList, { type OptionItem } from '../../lib/base/OptionList.svelte';
  import { checkThemeVars, type ContractReport } from '../../lib/base/theme-contract';
  import { guideThemes, onGuideTheme, paintScope, type GuideTheme } from '../theme-scope';

  const OPTIONS: OptionItem[] = [
    { value: 'a', label: 'keep it', reason: 'nothing to migrate', recommended: true },
    { value: 'b', label: 'replace it' },
  ];
  let themes = $state<GuideTheme[]>([]);

  $effect(() => onGuideTheme(() => (themes = guideThemes())));

  function scoped(theme: GuideTheme) {
    return (el: HTMLElement): void => paintScope(el, theme, themes);
  }

  function standing(r: ContractReport): string {
    const parts = [
      r.missing.length ? `missing ${r.missing.join(', ')}` : '',
      r.baseTokens.length ? `sets base tokens ${r.baseTokens.join(', ')}` : '',
      r.unknown.length ? `unknown ${r.unknown.join(', ')}` : '',
      r.badValues.length ? `bad ${r.badValues.join(', ')}` : '',
      r.deprecated.length ? `old names ${r.deprecated.join(', ')}` : '',
    ].filter(Boolean);
    return parts.length ? parts.join('; ') : 'keeps the contract';
  }
</script>

{#if themes.length === 0}
  <p class="sg-caption">waiting for the theme list</p>
{:else}
  <div class="sg-bct">
    {#each themes as theme (theme.id)}
      <div class="sg-bct__tile" {@attach scoped(theme)}>
        <Card title={theme.name} meta="base components" compact>
          {#snippet children()}
            <OptionList prompt="keep the old layout?" tag="required" options={OPTIONS} recommendedLabel="rec" value="a" />
            <Field label="other" placeholder="say it in your words" />
            <List density="dense" label="runs">
              <ListRow primary="nightly backup" secondary="02:00" meta="12s" selected>
                {#snippet actions()}<Button size="sm" variant="quiet">edit</Button>{/snippet}
              </ListRow>
              <ListRow primary="deploy check" secondary="every 15 minutes" meta="1m 04s" />
            </List>
            <State inline title="no runs yet" />
          {/snippet}
          {#snippet foot()}
            <Button size="sm">cancel</Button>
            <Button size="sm" variant="confirm">save</Button>
            <Button size="sm" variant="danger">remove</Button>
          {/snippet}
        </Card>
        <span class="sg-bct__contract" data-theme-contract={theme.id}>{standing(checkThemeVars(theme.cssVars))}</span>
      </div>
    {/each}
  </div>
{/if}
