<script lang="ts">
  /* the detail pane */
  import ManagerFrame from '../../lib/manager-frame/ManagerFrame.svelte';
  import { createManagerController } from '../../lib/manager-frame/manager-controller.svelte';
  import type { ManagerAdapter, ManagerFilter, ManagerItem } from '../../lib/manager-frame/types';
  import { MANAGER_KEYS } from '../../lib/manager-frame/manager-model';
  import type { Translate } from '../../lib/sessions/types';
  import { t as appT } from '../../lib/i18n/index.svelte';

  interface Props {
    part?: 'ready' | 'loading' | 'error' | 'empty';
    t?: Translate;
    refuseToggle?: boolean;
    /* the detail pane */
    share?: boolean;
    limits?: boolean;
  }

  const { part = 'ready', t = appT, refuseToggle = false, share = false, limits = false }: Props = $props();

  let stored: ManagerItem[] = [
    { id: 'mark-unread', name: 'mark unread', brief: 'mark a session unread from its menu', meta: '1.0.0, builtin', marks: ['builtin'], enabled: true, removeBlocked: 'a builtin plugin cannot be removed' },
    { id: 'open-as-component', name: 'open as component', brief: 'open a session inside a dashboard cell', meta: '1.1.0, builtin', marks: ['builtin'], enabled: false },
    { id: 'share-read-only', name: 'share read only', brief: 'hand out a view-only link to a session', meta: '0.9.2, nyedis', marks: ['network'], enabled: true },
    { id: 'notes-export', name: 'notes export', brief: 'save session notes as markdown', meta: '0.3.0, nyedis', enabled: null },
  ];

  const never = new Promise<readonly ManagerItem[]>(() => {});

  const adapter: ManagerAdapter = {
    list: () => {
      if (part === 'loading') return never;
      if (part === 'error') return Promise.reject(new Error('the server answered 503 while reading plugins'));
      return Promise.resolve(part === 'empty' ? [] : stored);
    },
    setEnabled: async (id, enabled) => {
      if (refuseToggle) throw new Error('this plugin is required by an open layout');
      stored = stored.map((item) => (item.id === id ? { ...item, enabled } : item));
      return stored.find((item) => item.id === id)!;
    },
  };

  // svelte-ignore state_referenced_locally
  if (share) {
    adapter.exportItem = async (id) => ({ filename: `${id}.plugin.json`, document: { id } });
    adapter.remove = async (id) => {
      stored = stored.filter((item) => item.id !== id);
    };
  }

  // svelte-ignore state_referenced_locally
  const ctl = createManagerController(adapter, t(MANAGER_KEYS.errorTitle), (filename) => filename);
  void ctl.load();

  let query = $state('');
  let builtinOnly = $state(false);
  // svelte-ignore state_referenced_locally
  let selectedId = $state<string | null>(share ? 'share-read-only' : null);

  const filters: ManagerFilter[] = $derived([
    {
      id: 'builtin',
      label: 'builtin',
      on: builtinOnly,
      test: (item: ManagerItem) => (item.marks ?? []).includes('builtin'),
    },
  ]);
</script>

<ManagerFrame
  embedded
  title="plugins"
  label="plugin"
  items={ctl.items}
  status={ctl.status}
  {query}
  onQuery={(next) => (query = next)}
  {filters}
  onFilter={(_id, on) => (builtinOnly = on)}
  onClearFilters={() => (builtinOnly = false)}
  {selectedId}
  onSelect={(id) => (selectedId = id)}
  onToggle={(id, next) => void ctl.toggle(id, next)}
  toggles={ctl.toggles}
  onRetry={() => void ctl.load()}
  onInstall={() => {}}
  onExport={share ? (id) => void ctl.exportItem(id) : undefined}
  onRemove={share ? (id) => void ctl.remove(id) : undefined}
  itemActions={ctl.actions}
  removed={ctl.removed}
  limits={limits ? ['plugins are built into this version of the app, so none can be installed or removed here.'] : []}
  {t}
>
  {#snippet detail(item)}
    <dl class="sg-facts">
      <dt>id</dt>
      <dd><code>{item.id}</code></dd>
      <dt>version</dt>
      <dd>{item.meta ?? ''}</dd>
    </dl>
  {/snippet}
</ManagerFrame>
