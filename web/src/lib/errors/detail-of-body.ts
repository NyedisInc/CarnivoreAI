
export function detailOfBody(body: unknown, reasonText: (reason: string) => string = (reason) => reason): string {
  if (!body || typeof body !== 'object') return '';
  const record = body as Record<string, unknown>;
  const detail = record['detail'];
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object') {
    const inner = detail as Record<string, unknown>;
    if (typeof inner['message'] === 'string' && inner['message']) return inner['message'];
    if (typeof inner['detail'] === 'string' && inner['detail']) return inner['detail'];
    if (typeof inner['reason'] === 'string' && inner['reason']) return reasonText(inner['reason']);
  }
  if (typeof record['message'] === 'string' && record['message']) return record['message'];
  return '';
}
