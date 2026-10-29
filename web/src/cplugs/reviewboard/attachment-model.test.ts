import { describe, expect, it } from 'vitest';
import { apiPathOf, openType } from './attachment-model';

describe('openType', () => {
  it('draws images, pdf and plain text as themselves', () => {
    expect(openType('image/png')).toBe('image/png');
    expect(openType('application/pdf')).toBe('application/pdf');
    expect(openType('text/plain; charset=utf-8')).toBe('text/plain');
  });

  it('never draws a type that can run script as itself: html, svg and xml show as plain text', () => {
    for (const mime of ['text/html', 'TEXT/HTML; charset=utf-8', 'image/svg+xml', 'application/xhtml+xml', 'text/xml', 'text/markdown']) {
      expect(openType(mime)).toBe('text/plain');
    }
  });

  it('saves a type with no safe view instead of opening it', () => {
    expect(openType('application/zip')).toBeNull();
    expect(openType('application/javascript')).toBeNull();
    expect(openType('')).toBeNull();
  });
});

describe('apiPathOf', () => {
  it('reads only the huddle file route with an 8 hex id, never another address', () => {
    expect(apiPathOf('/api/v1/cplugs/huddle/items/7/files/ab12cd34')).toBe('/cplugs/huddle/items/7/files/ab12cd34');
    expect(apiPathOf('https://elsewhere.test/api/v1/x')).toBeNull();
    expect(apiPathOf('/api/v1/../static/x')).toBeNull();
    expect(apiPathOf('/api/v1/cplugs/huddle/items/7/files/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/sessions/list')).toBeNull();
    expect(apiPathOf('/api/v1/sessions/list')).toBeNull();
    expect(apiPathOf('/api/v1/cplugs/huddle/items/7/files/ab12')).toBeNull();
    expect(apiPathOf('/api/v1/cplugs/huddle/items/7/files/ab12cd34?x=1')).toBeNull();
    expect(apiPathOf(null)).toBeNull();
  });
});
