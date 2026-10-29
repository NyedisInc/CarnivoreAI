import { accessToken, auth, hasRefreshToken, refreshTokens } from '../../opscenter/api/auth.svelte';

const BASE = '/api/v1';

export function featureMediaPath(featureId: string, file: string): string {
  return `${BASE}/feature-media/${encodeURIComponent(featureId)}/${encodeURIComponent(file)}`;
}

export async function fetchFeatureMediaBlob(
  featureId: string,
  file: string,
  retrying = false,
): Promise<Blob> {
  if (auth.state === 'signed-out') throw new Error('not signed in');
  const token = accessToken();
  const headers = new Headers();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(featureMediaPath(featureId, file), { headers });
  if (response.status === 401) {
    if (!retrying && hasRefreshToken()) {
      const rotated = await refreshTokens();
      if (rotated) return fetchFeatureMediaBlob(featureId, file, true);
    }
    throw new Error('not signed in');
  }
  if (!response.ok) {
    throw new Error(`feature media answered ${response.status}`);
  }
  return response.blob();
}
