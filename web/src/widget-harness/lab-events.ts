import topicsSource from '../../../src/core/resource_push/topics.py?raw';

export function advertisedTopics(source: string): string[] {
  const names = new Map<string, string>();
  for (const found of source.matchAll(/^([A-Z][A-Z0-9_]*)\s*=\s*"([^"]+)"/gm)) names.set(found[1]!, found[2]!);
  const tuple = /^RESOURCE_TOPICS[^=]*=\s*\(([\s\S]*?)^\)/m.exec(source);
  if (!tuple) return [];
  return [...tuple[1]!.matchAll(/[A-Z][A-Z0-9_]*/g)].map((one) => names.get(one[0])).filter((topic): topic is string => topic !== undefined);
}

function labEvents(): { subscribe(handler: (frame: { type?: string }) => void): () => void; isConnected(): boolean; lastHello(): { resource_topics: string[] } } {
  const hello = { type: 'events.hello', resource_topics: advertisedTopics(topicsSource) };
  return {
    lastHello: () => hello,
    subscribe(handler) {
      queueMicrotask(() => handler(hello));
      return () => undefined;
    },
    isConnected: () => true,
  };
}

const page = globalThis as { AppEvents?: unknown };
page.AppEvents ??= labEvents();
