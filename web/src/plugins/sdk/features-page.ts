
export const FEATURES_HASH = '#settings/features';

export function openFeaturesPage(): boolean {
  if (typeof window === 'undefined') return false;
  window.location.hash = FEATURES_HASH;
  return true;
}
