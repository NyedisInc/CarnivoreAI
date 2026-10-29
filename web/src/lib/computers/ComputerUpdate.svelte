<script lang="ts">
  import { onDestroy } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { Button } from '../base';
  import Check from '../../opscenter/ui/Check.svelte';
  import { auth, authFetch } from '../../opscenter/api/auth.svelte';
  import { resourcePush } from '../resource-push/boot';
  import { KNOWN_STATES, runUpdate, type UpdateAction, type UpdateView } from './computer-update';

  interface Props {
    hostKey: string;
    fetcher?: typeof authFetch;
  }
  const { hostKey, fetcher = authFetch }: Props = $props();

  let view = $state<UpdateView | null>(null);
  let busy = $state(false);
  let timer: ReturnType<typeof setTimeout> | undefined;

  const update = $derived(view?.kind === 'ok' ? view.update : null);
  const phase = $derived(update ? (KNOWN_STATES.includes(update.state) ? update.state : 'unavailable') : '');
  const canInstall = $derived(update?.attached === true && (phase === 'available' || phase === 'ready'));

  function take(next: UpdateView): void {
    view = next;
    clearTimeout(timer);
    if (next.kind === 'ok' && (next.update.state === 'checking' || next.update.state === 'downloading')) timer = setTimeout(() => void load(), 4000);
  }
  async function load(): Promise<void> {
    if (fetcher === authFetch && auth.state === 'signed-out') return;
    take(await runUpdate(fetcher, hostKey));
  }
  async function act(action: UpdateAction, enabled?: boolean): Promise<void> {
    busy = true;
    take(await runUpdate(fetcher, hostKey, action, enabled));
    busy = false;
  }
  void load();
  const stop = hostKey === '' ? resourcePush().pushOrPoll(() => void load(), 30000, ['app_update']) : () => undefined;
  onDestroy(() => {
    stop();
    clearTimeout(timer);
  });
</script>

<div data-cmp="update">
  {#if view?.kind === 'ok' && update}
    <div class="cmp-head">
      <span class="cmp-meta" data-cmp="app-version">{t('computers.update.version', { version: update.current_version })}</span>
      <span class="cmp-meta" role="status" data-cmp="update-state">
        {t(`settings.app_update.state.${phase}`, { version: update.latest_version, percent: update.percent ?? 0, detail: update.detail ?? '' })}
      </span>
      {#if canInstall}
        <Button size="sm" data-cmp="update-now" disabled={busy}
          onclick={() => void act('install')}>{t('settings.app_update.install')}</Button>
      {/if}
    </div>
    <Check label={t('settings.app_update.auto')} checked={update.auto_update} role="switch" disabled={busy} data-cmp="update-auto"
      onToggle={(next) => void act('auto', next)} />
  {:else if view?.kind === 'unsupported'}
    <p class="cmp-note" data-cmp="update-unsupported">{t('computers.update.unsupported')}</p>
  {:else if view?.kind === 'refused'}
    <p class="cmp-note" data-cmp="update-refused">{t(view.reason === 'pack_restricted' ? 'computers.update.restricted' : 'computers.update.refused')}</p>
  {:else if view?.kind === 'unavailable'}
    <p class="cmp-note" data-cmp="update-unavailable">{t('computers.update.unavailable')}</p>
  {/if}
</div>
