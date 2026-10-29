import { describe, expect, test } from 'vitest';
import { offersFor, pointOf } from './actions.svelte';
import { markOf, timelineFixture } from './fixture';

describe('what a mark\'s menu offers', () => {
  const data = timelineFixture();
  const at = (id: string) => data.marks.find((m) => m.id === id)!;

  test('a bookmark can always be cut, even from an earlier conversation, but not bookmarked again', () => {
    const earlier = markOf({ id: 'b', kind: 'bookmark', conversation_id: 'conv-a', entry_uuid: 'e', bookmark_id: 3, can_peek: true });
    expect(offersFor(earlier, data)).toEqual({ cut: true, bookmark: false, copy: false, peek: true });
    expect(pointOf(earlier)).toEqual({ bookmarkId: 3 });
  });

  test('a record of the current conversation can be cut and bookmarked; one of an earlier conversation cannot', () => {
    const here = markOf({ id: 'c', kind: 'compact', conversation_id: 'conv-c', entry_uuid: 'x', can_peek: true });
    expect(offersFor(here, data)).toMatchObject({ cut: true, bookmark: true });
    expect(pointOf(here)).toEqual({ entryUuid: 'x' });
    expect(offersFor(at('compact:conv-b:9'), data)).toMatchObject({ cut: false, bookmark: false, peek: true });
  });

  test('a restore point offers open a copy and nothing that cuts; a restart offers nothing but open', () => {
    expect(offersFor(at('restore:conv-b:20261010T112500Z-kill'), data)).toEqual({ cut: false, bookmark: false, copy: true, peek: false });
    expect(offersFor(at('restart:conv-c:2'), data)).toEqual({ cut: false, bookmark: false, copy: false, peek: false });
    expect(pointOf(at('restart:conv-c:2'))).toBeNull();
  });

  test('a Codex session takes no bookmark, cut or peek', () => {
    const codex = { ...data, family: 'codex' };
    expect(offersFor(at('bookmark:1'), codex)).toEqual({ cut: false, bookmark: false, copy: false, peek: false });
  });
});
