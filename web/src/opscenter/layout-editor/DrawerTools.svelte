<script lang="ts">
  import Field from '../../lib/base/Field.svelte';
  import Select from '../../lib/base/Select.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { WidgetType } from '../widgets/types';

  let {
    query = $bindable(),
    kind = $bindable(),
    kinds,
    addableCount,
  }: { query: string; kind: WidgetType | null; kinds: readonly WidgetType[]; addableCount: number } = $props();

  const kindOptions = $derived([
    { value: '', label: t('layout_editor.drawer.all_kinds') },
    ...kinds.map((one) => ({ value: one, label: t(`widgets.type.${one}`) })),
  ]);

  function onSearchKey(event: KeyboardEvent): void {
    if (event.key === 'Escape' && query) {
      event.preventDefault();
      event.stopPropagation();
      query = '';
    }
  }
</script>

  <div class="le-tools">
    <div class="le-find">
      <Field
        type="search"
        bind:value={query}
        aria-label={t('layout_editor.drawer.search_label')}
        placeholder={t('layout_editor.drawer.search_placeholder')}
        onkeydown={onSearchKey}
        data-layout-editor-search
      />
      <div class="le-kind">
        <Select
          size="sm"
          aria-label={t('layout_editor.drawer.kinds')}
          value={kind ?? ''}
          options={kindOptions}
          data-drawer-kind-filter
          onchange={(event) => {
            const picked = (event.currentTarget as HTMLSelectElement).value;
            kind = picked === '' ? null : (picked as WidgetType);
          }}
        />
      </div>
    </div>
    <p class="le-hint">{t(addableCount ? 'layout_editor.drawer.hint' : 'layout_editor.drawer.all_placed')}</p>
  </div>

<style>
  .le-find {
    display: flex;
    align-items: center;
    gap: var(--oc-space-2);
    min-width: 0;
  }

  .le-find :global([data-layout-editor-search]) {
    flex: 1 1 auto;
    min-width: 0;
  }

  .le-kind {
    display: flex;
    flex: 0 1 auto;
    max-width: 45%;
    min-width: 0;
  }
</style>
