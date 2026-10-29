import { browserPath } from '../../popout/popout';
import { browserById, type BrowserInfo } from './api.svelte';
import { BROWSER_ID } from './browser-id';
import { frameable } from './page-frame';
import { openPages, pageById } from './pages.svelte';

function inDesktopApp(win: Window): boolean {
  return 'carnivoreDesktop' in win;
}

export function openTab(url: string, win: Window): true {
  win.open(url, '_blank', 'noopener');
  return true;
}

function browserAddress(browser: Pick<BrowserInfo, 'id' | 'url'>): string {
  return /^https?:\/\//i.test(browser.url ?? '') ? browser.url : browserPath(browser.id);
}

async function openArtifact(id: string, win: Window, listFresh: boolean): Promise<boolean> {
  const desktop = inDesktopApp(win);
  const tab = desktop ? null : win.open('about:blank', '_blank');
  if (!desktop && !tab) return false;
  try {
    if (tab) tab.opener = null;
  } catch {
  }
  if (!listFresh) {
    try {
      await openPages.refresh(true);
    } catch (err) {
      console.warn('pop out: pages list refresh failed', err);
    }
  }
  const framed = frameable(pageById(id));
  if (!framed) {
    tab?.close();
    return false;
  }
  if (tab) {
    tab.location.href = framed.src;
    return true;
  }
  return openTab(framed.src, win);
}

export async function popOutItem(id: string, win: Window = window): Promise<boolean> {
  if (!BROWSER_ID.test(id)) return false;
  let page = pageById(id);
  let listFresh = false;
  if (!page) {
    const browser = browserById(id);
    if (browser) return openTab(browserAddress(browser), win);
    try {
      await openPages.refresh(true);
    } catch (err) {
      console.warn('pop out: pages list refresh failed', err);
    }
    listFresh = true;
    page = pageById(id);
    if (!page) return openTab(browserPath(id), win);
  }
  if (page.frame === 'sandboxed') return openArtifact(id, win, listFresh);
  const framed = frameable(page);
  return framed ? openTab(framed.src, win) : false;
}
