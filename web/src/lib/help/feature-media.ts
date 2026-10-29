import { API_BASE, auth, authFetchBlob } from '../../opscenter/api/auth.svelte';

const BASE = '/api/v1';

export function featureMediaPath(featureId: string, file: string): string {
  return `${BASE}/feature-media/${encodeURIComponent(featureId)}/${encodeURIComponent(file)}`;
}

export function fetchFeatureMediaBlob(featureId: string, file: string): Promise<Blob> {
  if (auth.state === 'signed-out') return Promise.reject(new Error('not signed in'));
  return authFetchBlob(featureMediaPath(featureId, file).slice(API_BASE.length));
}
