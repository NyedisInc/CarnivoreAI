
export const LINK_PREFIX = '#deepsearch/context';

export interface ContextLink {
  conversationId: string;
  line: number;
  fileKind: 'conversation' | 'subagent';
  hostKey: string | null;
}

export function linkHash(link: ContextLink): string {
  const params = new URLSearchParams({ c: link.conversationId, l: String(link.line) });
  if (link.fileKind === 'subagent') params.set('k', 'subagent');
  if (link.hostKey && link.hostKey !== 'local') params.set('h', link.hostKey);
  return `${LINK_PREFIX}?${params.toString()}`;
}

export function parseLink(hash: string): ContextLink | null {
  if (!hash.startsWith(`${LINK_PREFIX}?`)) return null;
  const params = new URLSearchParams(hash.slice(LINK_PREFIX.length + 1));
  const conversationId = params.get('c');
  const line = Number(params.get('l'));
  if (!conversationId || !params.has('l') || !Number.isInteger(line) || line < 0) return null;
  return { conversationId, line, fileKind: params.get('k') === 'subagent' ? 'subagent' : 'conversation', hostKey: params.get('h') || null };
}
