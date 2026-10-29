<script lang="ts">
  import { onDestroy } from 'svelte';
  import { t } from '../sdk';
  import { Button } from '../sdk/ui';
  import type { LabSize } from '../sdk/widget-lab';
  import { frameHeight, frameUrl, frameWindowWidth, SIDEBAR_WINDOW, type FrameSpec } from './frame-url';
  import type { HarnessWindow } from './frame-reader';
  import { measureIdle, type IdleReading } from './idle-read';

  interface Props {
    spec: FrameSpec;
    size: LabSize;
  }

  const { spec, size }: Props = $props();

  let phase = $state<'none' | 'running' | 'done' | 'failed'>('none');
  let reading = $state<IdleReading | null>(null);
  let frame = $state<HTMLIFrameElement | null>(null);
  let gone = false;
  onDestroy(() => (gone = true));

  const sidebar = $derived(spec.shell === 'sidebar');
  const width = $derived(sidebar ? SIDEBAR_WINDOW.w : frameWindowWidth(size));
  const height = $derived(sidebar ? SIDEBAR_WINDOW.h : frameHeight(size));
  const clean = $derived(reading !== null && reading.hidden === 0);
  const tip = $derived(reading === null ? t('cplug.devwidgetlab.idle.title') : reading.routes.length ? reading.routes.join(', ') : t('cplug.devwidgetlab.idle.clean'));

  function run(): void {
    reading = null;
    phase = 'running';
  }

  async function loaded(): Promise<void> {
    const win = frame?.contentWindow as (Window & HarnessWindow) | null | undefined;
    if (!win) return;
    try {
      reading = await measureIdle(win, () => gone);
    } catch (error) {
      console.warn('[widget lab] idle check', error);
      reading = null;
    }
    if (!gone) phase = reading ? 'done' : 'failed';
  }
</script>

<Button size="sm" data-idle-run disabled={phase === 'running'} title={t('cplug.devwidgetlab.idle.title')} onclick={run}>
  {phase === 'running' ? t('cplug.devwidgetlab.idle.running') : t('cplug.devwidgetlab.idle.run')}
</Button>
{#if phase === 'done' && reading}
  <span class="dwl-verdict" data-idle-result data-verdict={clean ? 'pass' : 'fail'} title={tip}>{t('cplug.devwidgetlab.idle.result', { hidden: reading.hidden, shown: reading.shown })}</span>
{:else if phase === 'failed'}
  <span class="dwl-verdict" data-idle-result data-verdict="fail">{t('cplug.devwidgetlab.idle.failed')}</span>
{/if}
{#if phase === 'running'}
  <iframe
    bind:this={frame}
    title={t('cplug.devwidgetlab.idle.run')}
    src={frameUrl({ ...spec, scenario: false, idle: true })}
    {width}
    {height}
    aria-hidden="true"
    tabindex="-1"
    style="position: fixed; left: -10000px; top: 0; border: 0; visibility: hidden;"
    onload={() => void loaded()}
  ></iframe>
{/if}
