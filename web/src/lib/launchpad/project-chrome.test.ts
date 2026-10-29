import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import {
    archivedNoticeText,
    authorityBannerText,
    PROJECT_TREE_KEYS,
} from '../../../../client/js/labels/project-tree.js';
import { archivedNotice, authorityBanner } from './project-chrome';

const i18n = createI18n({ locale: 'en' }) as {
    t(k: string, p?: Record<string, unknown> | null): string;
};
const t = (k: string, p?: Record<string, unknown> | null) => i18n.t(k, p);

describe('the archived notice: three outcomes, never two', () => {
    test('NOT ASKED renders nothing at all', () => {
        expect(archivedNotice(null, []).kind).toBe('silent');
        expect(archivedNoticeText(archivedNotice(null, []), t)).toBeNull();
    });

    test('ASKED AND ANSWERED with none archived renders a MEASURED ZERO', () => {
        const notice = archivedNotice(true, [{ name: 'a' }]);
        expect(notice).toEqual({ kind: 'count', count: 0 });
        expect(archivedNoticeText(notice, t)).toContain('0');
    });

    test('ASKED AND ANSWERED with some archived renders the count', () => {
        const notice = archivedNotice(true, [
            { name: 'a', archived_at: 'yes' },
            { name: 'b' },
            { name: 'c', archived_at: 'yes' },
        ]);
        expect(notice).toEqual({ kind: 'count', count: 2 });
        expect(archivedNoticeText(notice, t)).toContain('2');
    });

    test('A FAILED FETCH is cannot-determine and NEVER a zero', () => {
        const notice = archivedNotice(false, []);
        expect(notice.kind).toBe('unknown');
        const text = archivedNoticeText(notice, t) as string;
        expect(text).toContain('CANNOT BE DETERMINED');
        expect(text).not.toContain('0');
    });

    test('the failed and the measured-zero renderings are NOT the same string', () => {
        expect(archivedNoticeText(archivedNotice(false, []), t))
            .not.toBe(archivedNoticeText(archivedNotice(true, []), t));
    });

    test('the notice renders even when the project list is empty', () => {
        expect(archivedNoticeText(archivedNotice(true, []), t)).toBeTruthy();
        expect(archivedNoticeText(archivedNotice(false, []), t)).toBeTruthy();
    });
});

describe('the authority banner: the healthy case draws nothing', () => {
    test('a healthy db mode draws NO banner', () => {
        const banner = authorityBanner({ mode: 'db', degraded: false, writable: true });
        expect(banner.kind).toBe('none');
        expect(authorityBannerText(banner, t)).toBeNull();
    });

    test('a FAILED authority fetch renders CANNOT DETERMINE, never healthy', () => {
        const banner = authorityBanner(null);
        expect(banner.kind).toBe('unknown');
        expect(authorityBannerText(banner, t)).toBe(t(PROJECT_TREE_KEYS.authorityUnknown));
    });

    test('an undefined authority is treated exactly like a null one', () => {
        expect(authorityBanner(undefined).kind).toBe('unknown');
    });

    test('an unreadable datastore renders the SERVER\'s own sentence', () => {
        const banner = authorityBanner({
            mode: 'db_unreadable',
            degraded: true,
            writable: false,
            message: 'the datastore could not be read; writes are refused',
        });
        expect(banner).toEqual({
            kind: 'degraded',
            mode: 'db_unreadable',
            writable: false,
            message: 'the datastore could not be read; writes are refused',
        });
        expect(authorityBannerText(banner, t))
            .toBe('the datastore could not be read; writes are refused');
    });

    test('a degraded mode with NO message falls back to the mode token', () => {
        const banner = authorityBanner({ mode: 'db_unreadable', degraded: true });
        expect(authorityBannerText(banner, t)).toBe('db_unreadable');
    });

    test('NO state can produce two banners: the verdict is one of three', () => {
        const kinds = [
            authorityBanner(null).kind,
            authorityBanner({ degraded: false }).kind,
            authorityBanner({ degraded: true, mode: 'x', message: 'm' }).kind,
        ];
        expect(kinds).toEqual(['unknown', 'none', 'degraded']);
    });

    test('the unreadable banner denies that an empty list means zero projects', () => {
        expect(t(PROJECT_TREE_KEYS.authorityUnknown))
            .toContain('not a claim that anything is wrong');
    });

    test('the empty state does not tell the user to edit config.json', () => {
        expect(String(enCatalog['project.list.empty.hint'])).not.toContain('config');
        expect(String(enCatalog['project.authority.unknown'])).not.toContain('config.json');
    });
});

describe('every key this surface asks for exists', () => {
    test.each(Object.values(PROJECT_TREE_KEYS))('%s is in the catalog', (key) => {
        expect(
            Object.prototype.hasOwnProperty.call(enCatalog, key as string),
            key as string,
        ).toBe(true);
    });
});
