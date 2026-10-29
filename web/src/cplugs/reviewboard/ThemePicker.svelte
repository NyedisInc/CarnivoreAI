<script lang="ts">
  import { t } from '../sdk';
  import { flatChoices, type ThemeGroup } from './board-theme';

  interface Props {
    groups: readonly ThemeGroup[];
    value: string;
    active: string | null;
    onchange: (id: string) => void;
    onrefresh: () => void;
  }

  let { groups, value, active, onchange, onrefresh }: Props = $props();

  const activeName = $derived(flatChoices(groups).find((c) => c.id === active)?.name ?? active ?? '');
</script>

<select class="oc-field rb-theme" aria-label={t('cplug.reviewboard.theme.label')} title={t('cplug.reviewboard.theme.title')} data-theme-picker
        {value} onfocus={onrefresh} onchange={(e) => onchange((e.currentTarget as HTMLSelectElement).value)}>
  <option value="" selected={value === ''}>{activeName ? t('cplug.reviewboard.theme.app_named', { name: activeName }) : t('cplug.reviewboard.theme.app')}</option>
  {#if groups.length > 1}
    {#each groups as group (group.source.id)}
      <optgroup label={group.source.label}>
        {#each group.choices as one (one.id)}
          <option value={one.id} selected={value === one.id}>{one.name}</option>
        {/each}
      </optgroup>
    {/each}
  {:else}
    {#each flatChoices(groups) as one (one.id)}
      <option value={one.id} selected={value === one.id}>{one.name}</option>
    {/each}
  {/if}
</select>
