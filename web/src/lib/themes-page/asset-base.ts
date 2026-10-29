export function themeAssetBase(source: string, id: string): string {
  const root = source === 'user' ? '/themes/' : '/static/css/themes/';
  return root + encodeURIComponent(id);
}
