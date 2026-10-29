<!-- get more on warez -->
<script lang="ts">
  import { Button } from '../base';
  import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
  import ManagerFrame from '../manager-frame/ManagerFrame.svelte';
  import { t } from '../i18n/index.svelte';
  import { openCatalogScreen } from '../catalog/screen-host';
  import './mods.css';
  import '../catalog/warez-card.css';
  import { createModActions } from './mod-actions.svelte';
  import ModNotices from './ModNotices.svelte';
  import ModRow from './ModRow.svelte';
  import { data, follow } from './store.svelte';

  let { embedded = false, focusId = null, onGetMore, onSelect }: { embedded?: boolean; focusId?: string | null; onGetMore?: () => void; onSelect?: (id: string) => void } = $props();

  // svelte-ignore state_referenced_locally
  let open = $state(embedded);
  let opener: HTMLElement | null = null;
  const actions = createModActions();

  const mods = $derived(data.list?.mods ?? []);
  const locked = $derived(data.list?.accounts.status === 'accounts_unreadable');
  const count = $derived(t(mods.length === 1 ? 'mods.page.count_one' : 'mods.page.count', { count: mods.length }));

  $effect(() => (open ? follow() : undefined));

  export function show(): void {
    if (open) return;
    opener = captureOpener();
    open = true;
  }

  export function close(): void {
    if (!open) return;
    open = false;
    restoreOpenerFocus(opener);
    opener = null;
  }

  export function isOpen(): boolean {
    return open;
  }
</script>

{#if open}
  <ManagerFrame
    title={t('mods.page.title')}
    label={count}
    lede={t('mods.page.new_sessions')}
    items={[]}
    status={{ kind: 'ready' }}
    query=""
    onQuery={() => {}}
    searchable={false}
    showCount={false}
    onClose={embedded ? undefined : close}
    {embedded}
    {t}
  >
    {#snippet body()}
      <div class="mods-page" data-mods>
        <ModNotices list={data.list} notice={actions.notice} />

        {#if data.status === 'loading'}
          <p class="mods-line" role="status">{t('mods.page.loading')}</p>
        {:else if data.status === 'error'}
          <p class="mods-line mods-line--error" role="alert" data-mods-error>{t('mods.page.read_failed', { reason: data.error })}</p>
        {:else if mods.length === 0}
          <p class="mods-line" role="status" data-mods-empty>{t('mods.page.empty')}</p>
        {:else}
          <ul class="mods-list warez-grid" aria-label={t('mods.page.list')} data-mod-list>
            {#each mods as mod (mod.mod_id)}
              <ModRow
                card
                {mod}
                {locked}
                selected={mod.mod_id === focusId}
                onSelect={() => onSelect?.(mod.mod_id)}
                busy={actions.busyId === mod.mod_id}
                onToggle={(next) => actions.toggle(mod, next)}
                onRemove={() => actions.remove(mod)}
              />
            {/each}
          </ul>
        {/if}

        <p class="mods-more">
          <Button data-mods-get-more onclick={() => (onGetMore ? onGetMore() : openCatalogScreen({ kind: 'mod' }))}>{t('mods.page.get_more')}</Button>
        </p>
      </div>
    {/snippet}
  </ManagerFrame>
{/if}
