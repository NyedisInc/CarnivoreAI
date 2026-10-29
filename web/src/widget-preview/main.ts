/* the widget harness page */
import { previewConfig, serveFixture } from './sandbox';
import '../app.css';
import '../opscenter/app.css';
import './preview.css';
import { mountPanel } from '../lib/mount';
import Harness from '../widget-harness/Harness.svelte';
import { harnessWidget } from '../widget-harness/catalog';
import { bindSessionFor } from '../widget-harness/bound-session';
import { paintTheme } from '../widget-harness/paint-theme';
import { fixtureFor } from '../opscenter/widgets/fixtures';
import { initAuth, startActivity } from '../opscenter/api';
import { startClock } from '../opscenter/lib/frozen-clock.svelte';
import { pinGridViewport } from '../opscenter/engine/viewport.svelte';
import { refreshAnalytics } from '../opscenter/cells/analytics/state.svelte';
import { PREVIEW_CLASSIC_SCRIPTS } from './protocol';
import type { StandardSize } from '../opscenter/widgets/standard-sizes';

const CONTAINER = 'widget-preview';

async function loadClassicScripts(urls: readonly string[]): Promise<void> {
  for (const src of urls) {
    await new Promise<void>((resolve) => {
      const script = document.createElement('script');
      script.src = src;
      script.async = false;
      script.onload = () => resolve();
      script.onerror = () => {
        console.warn('[widget-preview] script did not load', src);
        resolve();
      };
      document.head.append(script);
    });
  }
}

async function boot(): Promise<void> {
  const config = previewConfig;
  const widget = config ? harnessWidget(config.key) : undefined;
  if (!config || !widget) {
    console.warn('[widget-preview] nothing to draw', config?.key ?? '(no config)');
    return;
  }
  if (config.mode === 'sample') {
    serveFixture(fixtureFor(config.key, 'data'));
    bindSessionFor(config.key);
  }
  await loadClassicScripts(PREVIEW_CLASSIC_SCRIPTS);
  if (config.theme) await paintTheme(config.theme).catch((error: unknown) => console.warn('[widget-preview] theme', error));
  initAuth();
  startClock();
  pinGridViewport();
  startActivity();
  if (config.key.startsWith('core.analytics:')) await refreshAnalytics();
  const size: StandardSize = { name: config.size.name as StandardSize['name'], w: config.size.w, h: config.size.h, viewport: config.size.w };
  mountPanel(CONTAINER, Harness as never, { widget, zone: config.zone, size });
}

boot().catch((error: unknown) => console.warn('[widget-preview] draw failed', error));
