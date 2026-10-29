import { themeAssetBase } from '../lib/themes-page/asset-base';

let paintedNames: string[] = [];

export async function paintTheme(id: string): Promise<void> {
  document.documentElement.dataset['theme'] = id;
  let response = await fetch(`${themeAssetBase('builtin', id)}/theme.json`);
  if (response.status === 404) response = await fetch(`${themeAssetBase('user', id)}/theme.json`);
  if (!response.ok) throw new Error(`theme ${id} answered ${response.status}`);
  const manifest = (await response.json()) as { cssVars?: Record<string, string> };
  for (const name of paintedNames) document.documentElement.style.removeProperty(name);
  paintedNames = [];
  for (const [name, value] of Object.entries(manifest.cssVars ?? {})) {
    if (!name.startsWith('--')) continue;
    document.documentElement.style.setProperty(name, value);
    paintedNames.push(name);
  }
}
