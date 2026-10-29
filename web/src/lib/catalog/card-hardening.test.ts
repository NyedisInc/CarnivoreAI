import { describe, expect, test } from 'vitest';

import {
    MAX_BRIEF_CHARS,
    MAX_HEADLINE_CHARS,
    MAX_NAME_CHARS,
    MAX_PUBLISHER_CHARS,
    MAX_SUMMARY_CHARS,
    MAX_TAGS,
    MAX_TAG_CHARS,
    MAX_VERSION_CHARS,
    cardView,
    cardViews,
} from './card';
import { MAX_RULE_CHARS } from './grade';
import type { CatalogItem } from './types';

function keysOf(items: CatalogItem[]): string[] {
    return cardViews(items, false).map((card) => card.renderKey);
}

function distinct(values: string[]): number {
    return new Set(values).size;
}

describe('a render key that two index rows cannot collide on', () => {
    test('two items sharing one id still get two keys', () => {
        const items: CatalogItem[] = [{ id: 'a/b' }, { id: 'a/b' }];
        expect(distinct(items.map((item) => String(item.id)))).toBe(1);
        const keys = keysOf(items);
        expect(keys).toHaveLength(2);
        expect(distinct(keys)).toBe(2);
    });

    test('items carrying no id at all are told apart', () => {
        const keys = keysOf([{}, {}, { id: null }]);
        expect(distinct(keys)).toBe(3);
        expect(keys.every((key) => key.length > 0)).toBe(true);
    });

    test('an id crafted to look like a generated key still resolves', () => {
        expect(distinct(keysOf([{ id: 'a' }, { id: 'a' }, { id: 'a#1' }]))).toBe(3);
        expect(distinct(keysOf([{ id: 'a' }, { id: 'a#2' }, { id: 'a' }]))).toBe(3);
        expect(distinct(keysOf([{ id: '#0' }, {}, { id: '#0#1' }]))).toBe(3);
    });

    test('a unique id IS the key, so a row keeps its node across a refetch', () => {
        expect(keysOf([{ id: 'a/b' }, { id: 'c/d' }])).toEqual(['a/b', 'c/d']);
    });

    test('an empty listing is an empty list, not a row', () => {
        expect(cardViews([], false)).toEqual([]);
        expect(cardViews(null, false)).toEqual([]);
    });

    test('the untrusted flag is carried through the list mapper unchanged', () => {
        expect(cardViews([{ id: 'a' }], true).map((card) => card.untrusted)).toEqual([true]);
        expect(cardViews([{ id: 'a' }], false).map((card) => card.untrusted)).toEqual([false]);
    });
});

describe('tags, which one item can repeat as many times as it likes', () => {
    test('a tag repeated on ONE item is listed once', () => {
        const card = cardView({ card: { tags: ['cli', 'cli', 'web'] } }, false);
        expect(card.tags).toEqual(['cli', 'web']);
    });

    test('a repeat that differs only in whitespace is the same tag', () => {
        expect(cardView({ card: { tags: ['cli', ' cli '] } }, false).tags).toEqual(['cli']);
    });

    test('at most MAX_TAGS reach the row', () => {
        const many = Array.from({ length: 200 }, (_, i) => `t${i}`);
        expect(cardView({ card: { tags: many } }, false).tags).toHaveLength(MAX_TAGS);
    });

    test('one tag is clipped to MAX_TAG_CHARS', () => {
        const tag = cardView({ card: { tags: ['x'.repeat(4096)] } }, false).tags;
        expect(tag?.[0]).toHaveLength(MAX_TAG_CHARS);
    });

    test('a tag that is not a string is not a tag', () => {
        const tags = cardView(
            { card: { tags: [1, null, {}, 'ok', '   '] as unknown as string[] } },
            false,
        ).tags;
        expect(tags).toEqual(['ok']);
    });

    test('no tags array at all stays null, and an empty one stays empty', () => {
        expect(cardView({ card: {} }, false).tags).toBe(null);
        expect(cardView({ card: { tags: [] } }, false).tags).toEqual([]);
    });
});

describe('a megabyte of prose never reaches the document', () => {
    const huge = 'x'.repeat(1024 * 1024);

    test('the headline is clipped and says that it was', () => {
        const card = cardView({ card: { title: huge } }, false);
        expect(card.headline).toHaveLength(MAX_HEADLINE_CHARS);
        expect(card.headline?.endsWith('...')).toBe(true);
    });

    test('the brief is clipped', () => {
        expect(cardView({ card: { brief: huge } }, false).brief).toHaveLength(MAX_BRIEF_CHARS);
    });

    test('the review summary is clipped', () => {
        const card = cardView(
            { latest: '1', versions: [{ v: '1', review: { status: 'reviewed', summary: huge } }] },
            false,
        );
        expect(card.reviewSummary).toHaveLength(MAX_SUMMARY_CHARS);
    });

    test('the name, the publisher and the version are clipped', () => {
        const card = cardView({ name: huge, publisher: huge, latest: huge }, false);
        expect(card.name).toHaveLength(MAX_NAME_CHARS);
        expect(card.publisher).toHaveLength(MAX_PUBLISHER_CHARS);
        expect(card.version).toHaveLength(MAX_VERSION_CHARS);
    });

    test('the id is NOT clipped, because it is what an install is addressed by', () => {
        expect(cardView({ id: huge }, false).id).toHaveLength(huge.length);
    });

    test('a headline falls back to the id, CLIPPED, so the raw id is never painted', () => {
        const card = cardView({ id: huge }, false);
        expect(card.headline).toHaveLength(MAX_HEADLINE_CHARS);
    });

    test('NEGATIVE CONTROL: a short value is returned whole, with no marker', () => {
        const card = cardView({ card: { title: 'tidy', brief: 'does one thing' } }, false);
        expect(card.headline).toBe('tidy');
        expect(card.brief).toBe('does one thing');
    });

    test('a clip never splits a surrogate pair into half a character', () => {
        const card = cardView({ card: { tags: ['\u{1F600}'.repeat(200)] } }, false);
        const tag = card.tags?.[0] ?? '';
        expect(Array.from(tag)).toHaveLength(MAX_TAG_CHARS);
        expect(tag.includes('�')).toBe(false);
    });
});

describe('the grade letter is bounded, and an unreadable one is never guessed', () => {
    test('a letter longer than the bound is clipped, not dropped', () => {
        const huge = 'A'.repeat(500);
        const card = cardView(
            { latest: '1.0', versions: [{ v: '1.0', grade: { grade: huge, checked: 1, failed: [] } }] },
            false,
        );
        expect(card.gradeShape).toBe('graded');
        expect(card.gradeLetter).toHaveLength(MAX_RULE_CHARS);
    });

    test('NEGATIVE CONTROL: a non-string letter is absent, never guessed', () => {
        const numeric = cardView(
            { latest: '1.0', versions: [{ v: '1.0', grade: { grade: 12 as unknown as string } }] },
            false,
        );
        expect(numeric.gradeShape).toBe('absent');
        const nullLetter = cardView(
            { latest: '1.0', versions: [{ v: '1.0', grade: { grade: null } }] },
            false,
        );
        expect(nullLetter.gradeShape).toBe('absent');
    });

    test('a letter this build has never seen is still painted', () => {
        const card = cardView(
            { latest: '1.0', versions: [{ v: '1.0', grade: { grade: 'S', checked: 1, failed: [] } }] },
            false,
        );
        expect(card.gradeShape).toBe('graded');
        expect(card.gradeLetter).toBe('S');
    });
});
