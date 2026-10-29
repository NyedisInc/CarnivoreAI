<script lang="ts">
  import { t } from '../sdk';
  import { Button, Field } from '../sdk/ui';
  import { parseScenario } from '../sdk/widget-lab';

  interface Props {
    text: string;
    applied: string | null;
    fixtureJson: string;
    onapply: (text: string) => void;
    onclear: () => void;
  }

  let { text = $bindable(), applied, fixtureJson, onapply, onclear }: Props = $props();

  const checked = $derived(text.trim() === '' ? null : parseScenario(text));
  const pending = $derived(applied !== null && applied !== text);
</script>

<div class="dwl-scenario">
  <p class="dwl-hint">{t('cplug.devwidgetlab.scenario.hint')}</p>
  <Field multiline rows={8} spellcheck={false} data-scenario-text aria-label={t('cplug.devwidgetlab.scenario.title')} bind:value={text} />
  {#if checked?.ok}
    <p class="dwl-note dwl-note--ok">{t('cplug.devwidgetlab.scenario.valid', { count: checked.routes })}</p>
  {:else if checked}
    <p class="dwl-note dwl-note--error">{checked.error}</p>
  {/if}
  <div class="dwl-host-actions">
    <Button variant="confirm" size="sm" disabled={!checked?.ok} onclick={() => onapply(text)}>
      {t('cplug.devwidgetlab.scenario.apply')}
    </Button>
    <Button size="sm" disabled={applied === null} onclick={onclear}>{t('cplug.devwidgetlab.scenario.clear')}</Button>
    <Button size="sm" disabled={fixtureJson === ''} onclick={() => (text = fixtureJson)}>
      {t('cplug.devwidgetlab.scenario.load')}
    </Button>
  </div>
  {#if applied !== null}
    <p class="dwl-note">{pending ? t('cplug.devwidgetlab.scenario.pending') : t('cplug.devwidgetlab.scenario.applied')}</p>
  {/if}
</div>
