
export const DRAWER_ROOT_IDS: readonly string[] = [
  'session-sidebar-backdrop',
  'session-sidebar-panel',
  'session-sidebar-rail',
  'session-sidebar-account-menu',
];

const OWN_BUNDLE_CSS = '/static/dist/app.css';

export const FIXTURE_APP_VERSION = '1.0.0';

const LAST_SHEET = '/static/css/popup-focus.css';

export const DRAWER_SCRIPTS: readonly string[] = [
  'preferences', 'preference-bridge', 'kebab-icon', 'session-key', 'session-label', 'session-model-icon', 'effort-level', 'wrapper-mark', 'agent-family-icon', 'session-status-summary',
  'session-sidebar-row-controls', 'session-sidebar-keep-awake', 'session-sidebar-subagents',
  'session-sidebar-timers', 'session-sidebar-project-header', 'session-sidebar-groups', 'session-sidebar-group-colour', 'session-sidebar-group-icon',
  'session-sidebar-heading-actions', 'version-footer',
  'session-transport', 'session-row-actions-confirm', 'session-row-actions', 'session-row-menu-icons', 'text-prompt-modal', 'session-row-menu-items',
  'session-row-menu-plugins', 'session-row-menu', 'session-row-menu-actions', 'session-row-menu-sleep', 'session-row-menu-open', 'session-row-menu-gestures',
  'session-row-menu-shift',
];

export const DRAWER_MODULES: readonly string[] = ['i18n/boot'];

export interface DrawerMarkup {
  roots: Readonly<Record<string, string>>;
  ids: readonly string[];
  sheets: readonly string[];
  scripts: readonly string[];
  modules: readonly string[];
}

export function sheetPath(href: string): string | null {
  const path = href.split('?')[0] ?? '';
  return path.startsWith('/static/') && path.endsWith('.css') ? path : null;
}

export function parseDrawerMarkup(html: string): DrawerMarkup {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  const roots: Record<string, string> = {};
  const ids: string[] = [];
  for (const id of DRAWER_ROOT_IDS) {
    const el = doc.getElementById(id);
    if (!el) continue;
    for (const script of el.querySelectorAll('script')) script.remove();
    roots[id] = el.outerHTML;
    ids.push(id, ...[...el.querySelectorAll('[id]')].map((one) => one.id));
  }
  if (!roots['session-sidebar-panel']) throw new Error('the page has no #session-sidebar-panel to import');
  const sheets: string[] = [];
  for (const link of doc.querySelectorAll('link[rel="stylesheet"]')) {
    const path = sheetPath(link.getAttribute('href') ?? '');
    if (path && path !== OWN_BUNDLE_CSS && !sheets.includes(path)) sheets.push(path);
  }
  const scripts: string[] = [];
  for (const tag of doc.querySelectorAll('script[src]')) {
    const path = (tag.getAttribute('src') ?? '').split('?')[0] ?? '';
    const name = /^\/static\/js\/([a-z0-9-]+)\.js$/.exec(path)?.[1];
    if (name && DRAWER_SCRIPTS.includes(name) && !scripts.includes(path) && !tag.hasAttribute('type')) scripts.push(path);
  }
  const modules: string[] = [];
  for (const tag of doc.querySelectorAll('script[type="module"][src]')) {
    const path = (tag.getAttribute('src') ?? '').split('?')[0] ?? '';
    const name = /^\/static\/js\/(.+)\.js$/.exec(path)?.[1];
    if (name && DRAWER_MODULES.includes(name) && !modules.includes(path)) modules.push(path);
  }
  return { roots, ids: ids.sort(), sheets, scripts, modules };
}

let pageText: Promise<string> | null = null;

export function fetchPageText(fetcher: typeof fetch = fetch): Promise<string> {
  pageText ??= fetcher('/static/index.html', { credentials: 'omit' }).then((response) => {
    if (!response.ok) throw new Error(`the page /static/index.html answered ${response.status}`);
    return response.text();
  });
  return pageText;
}

export function forgetPageText(): void {
  pageText = null;
}

export async function adoptSheets(doc: Document, sheets: readonly string[]): Promise<void> {
  const have = new Set([...doc.querySelectorAll('link[rel="stylesheet"]')].map((link) => sheetPath(link.getAttribute('href') ?? '')));
  const last = [...doc.querySelectorAll('link[rel="stylesheet"]')].find((link) => sheetPath(link.getAttribute('href') ?? '') === LAST_SHEET) ?? null;
  const loading: Promise<void>[] = [];
  for (const path of sheets) {
    if (have.has(path) || path === LAST_SHEET) continue;
    const link = doc.createElement('link');
    link.rel = 'stylesheet';
    link.href = path;
    loading.push(new Promise<void>((resolve, reject) => {
      link.onload = () => resolve();
      link.onerror = () => reject(new Error(`stylesheet ${path} did not load`));
    }));
    if (last) last.before(link);
    else doc.head.append(link);
  }
  await Promise.all(loading);
}

export async function adoptScripts(doc: Document, scripts: readonly string[]): Promise<void> {
  const have = new Set([...doc.querySelectorAll('script[src]:not([type="module"])')].map((tag) => (tag.getAttribute('src') ?? '').split('?')[0]));
  for (const path of scripts) {
    if (have.has(path)) continue;
    await new Promise<void>((resolve, reject) => {
      const tag = doc.createElement('script');
      tag.src = path;
      tag.async = false;
      tag.onload = () => resolve();
      tag.onerror = () => reject(new Error(`script ${path} did not load`));
      doc.head.append(tag);
    });
  }
}

export async function adoptModules(modules: readonly string[]): Promise<void> {
  for (const path of modules) {
    try {
      await import(/* @vite-ignore */ path);
    } catch (error) {
      throw new Error(`module ${path} did not load: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
}

/*  hidden  */
export function adoptDrawer(doc: Document, markup: DrawerMarkup): void {
  if (doc.getElementById('session-sidebar-panel')) return;
  if (!doc.querySelector('meta[name="cloude-app-version"]')) {
    const meta = doc.createElement('meta');
    meta.name = 'cloude-app-version';
    meta.content = FIXTURE_APP_VERSION;
    doc.head.append(meta);
  }
  const toggle = doc.createElement('button');
  toggle.id = 'session-sidebar-toggle';
  toggle.type = 'button';
  toggle.className = 'session-sidebar-toggle hidden';
  toggle.setAttribute('aria-label', 'toggle the agents drawer');
  toggle.tabIndex = -1;
  toggle.style.display = 'none';
  doc.body.append(toggle);
  for (const id of DRAWER_ROOT_IDS) {
    const html = markup.roots[id];
    if (!html) continue;
    const holder = doc.createElement('template');
    holder.innerHTML = html;
    doc.body.append(doc.importNode(holder.content, true));
  }
}

export async function importRealDrawer(doc: Document = document, fetcher: typeof fetch = fetch): Promise<DrawerMarkup> {
  const markup = parseDrawerMarkup(await fetchPageText(fetcher));
  await adoptSheets(doc, markup.sheets);
  adoptDrawer(doc, markup);
  await adoptModules(markup.modules);
  await adoptScripts(doc, markup.scripts);
  return markup;
}
