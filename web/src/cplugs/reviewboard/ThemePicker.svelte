<script lang="ts">
  import { t } from '../sdk';
  import { Select, type SelectChoice } from '../sdk/ui';
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
  const choices = $derived<SelectChoice[]>([
    { value: '', label: activeName ? t('cplug.reviewboard.theme.app_named', { name: activeName }) : t('cplug.reviewboard.theme.app') },
    ...(groups.length > 1
      ? groups.map((group) => ({ group: group.source.label, options: group.choices.map((one) => ({ value: one.id, label: one.name })) }))
      : flatChoices(groups).map((one) => ({ value: one.id, label: one.name }))),
  ]);
</script>

<Select size="sm" value={value} options={choices} aria-label={t('cplug.reviewboard.theme.label')} title={t('cplug.reviewboard.theme.title')} data-theme-picker
          onfocus={onrefresh} onchange={(e) => onchange((e.currentTarget as HTMLSelectElement).value)} />
