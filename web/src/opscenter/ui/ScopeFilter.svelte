<script lang="ts">
  import Segmented from '../../lib/base/Segmented.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import { SCOPES, type Scope } from './scope-filter';

  interface Props {
    value: Scope;
    onChange: (scope: Scope) => void;
    label: string;
  }

  let { value, onChange, label }: Props = $props();

  const options = $derived(SCOPES.map((scope) => ({ value: scope, label: t(`opscenter.scope.${scope}`), attrs: { 'data-scope': scope } })));
</script>

<Segmented {label} bind:value={() => value, (next) => onChange(next as Scope)} options={options} data-scope-filter />
