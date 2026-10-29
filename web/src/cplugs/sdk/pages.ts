
const openers = new Map<string, () => boolean>();

export function registerCplugPage(id: string, open: () => boolean): void {
  openers.set(id, open);
}

export function openCplugPage(id: string): boolean {
  return openers.get(id)?.() ?? false;
}

export { openPluginsScreen as openPluginsPage } from '../../lib/plugins-page/screen-host';
