<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import Button from '../base/Button.svelte';
  import Field from '../base/Field.svelte';
  import { needsApi, type NeedsApi, type NeedsBody, type NeedsView } from './needs-api';

  let { name, api = needsApi }: { name: string; api?: NeedsApi } = $props();

  let view = $state<NeedsView | null>(null);
  let draft = $state<Record<string, { needs: string; prefer: string }>>({});
  let busy = $state(false);
  let error = $state<string | null>(null);

  const words = (text: string): string[] => text.split(/[\s,]+/).filter(Boolean);
  const join = (list: string[]): string => list.join(' ');
  const changed = (kind: string): boolean => {
    const own = view?.kinds[kind];
    const typed = draft[kind];
    return !!own && !!typed && (join(words(typed.needs)) !== join(own.needs) || join(words(typed.prefer)) !== join(own.prefer));
  };
  const anyChanged = $derived(!!view && Object.keys(view.kinds).some(changed));

  async function load(): Promise<void> {
    try {
      const next = await api.read(name);
      view = next;
      draft = Object.fromEntries(Object.entries(next.kinds).map(([kind, k]) => [kind, { needs: join(k.needs), prefer: join(k.prefer) }]));
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.needs.error.failed'));
    }
  }

  async function send(body: NeedsBody): Promise<void> {
    if (busy) return;
    busy = true;
    error = null;
    try {
      await api.write(name, body);
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.needs.error.failed'));
    } finally {
      busy = false;
      await load();
    }
  }

  const save = (): Promise<void> => send(Object.fromEntries(Object.keys(view?.kinds ?? {}).filter(changed)
    .map((kind) => [kind, { needs: words(draft[kind]!.needs), prefer: words(draft[kind]!.prefer) }])));

  void load();
</script>

<div class="pt-needs" data-pt="needs">
  <h4 class="oc-label">{t('pack.needs.title')}</h4>
  {#if error}<p class="pt-error" role="alert" data-pt="needs-error">{error}</p>{/if}
  {#if view}
    <p class="pt-note">{t('pack.needs.help')}</p>
    <p class="pt-note" data-pt="needs-vocab">{t('pack.needs.vocab', { words: view.vocabulary.join(', ') })}</p>
    {#each Object.entries(view.kinds) as [kind, own] (kind)}
      <div class="pt-needs-kind" data-pt="needs-kind" data-kind={kind}>
        <span class="oc-sub">{kind}</span>
        <div class="pt-needs-words">
          <Field label={t('pack.needs.needs')} bind:value={draft[kind]!.needs} disabled={busy} data-pt="needs-input" />
          <Field label={t('pack.needs.prefer')} bind:value={draft[kind]!.prefer} disabled={busy} data-pt="needs-prefer" />
        </div>
        {#if own.stored}
          <Button size="sm" style="align-self: flex-start" disabled={busy} data-pt="needs-reset" onclick={() => void send({ [kind]: null })}>{t('pack.needs.reset')}</Button>
        {:else}
          <p class="pt-note" data-pt="needs-default">{t('pack.needs.default', { needs: join(own.default_filters) || t('pack.needs.nothing'), prefer: join(own.default_prefer) || t('pack.needs.nothing') })}</p>
        {/if}
      </div>
    {/each}
    <div class="pt-actions">
      <Button variant="confirm" disabled={busy || !anyChanged} data-pt="needs-save" onclick={() => void save()}>{t('pack.needs.save')}</Button>
    </div>
  {:else if !error}
    <p class="pt-note">{t('pack.transport.loading')}</p>
  {/if}
</div>
