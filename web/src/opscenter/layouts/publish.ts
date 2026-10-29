import { layoutPageApi, start } from './page.svelte';

start();

queueMicrotask(() => {
  const web = (globalThis as { CloudeWeb?: Record<string, unknown> }).CloudeWeb;
  if (web && !('layoutPage' in web)) web['layoutPage'] = layoutPageApi;
});
