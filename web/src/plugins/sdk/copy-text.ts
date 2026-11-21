export function copyToClipboard(text: string): Promise<boolean> {
  const g = globalThis as {
    CopyCompat?: { copyText(value: string): Promise<{ ok: boolean }> };
    navigator?: { clipboard?: { writeText(value: string): Promise<void> } };
  };
  if (g.CopyCompat) return g.CopyCompat.copyText(text).then((r) => r.ok, () => false);
  const clip = g.navigator?.clipboard;
  if (clip && typeof clip.writeText === 'function') return clip.writeText(text).then(() => true, () => false);
  return Promise.resolve(false);
}
