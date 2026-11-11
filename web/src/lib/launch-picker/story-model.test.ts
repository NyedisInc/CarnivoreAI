import { describe, expect, it } from 'vitest';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { buildOpenProjectPayload } from '../launchpad/open-project-payload';
import { buildCreatePayload } from '../launchpad/create-flow';
import { candidatesOf, groupItems, hasChoices, rowVisible, storyAnswer, type WorkItem } from './story-model';

const item = (id: string, title: string, sprint: string, at: string, kind = 'story'): WorkItem => ({ id, kind, parent_id: null, title, sprint_state: sprint, updated_at: at });

describe('the launch picker story row (argent P7b)', () => {
    it('groups active first, then the newest others, then the rest by title, and filters by title', () => {
        const items = [
            item('a1', 'old active', 'active', '2026-01-01'), item('a2', 'new active', 'active', '2026-02-01'),
            ...['b', 'c', 'd', 'e', 'f'].map((k, n) => item(k, `other ${k}`, 'future', `2026-03-0${n + 1}`)),
            item('z', 'zzz old', 'none', '2025-01-01'), item('y', 'aaa old', 'closed', '2025-01-02'),
        ];
        const groups = groupItems(items, '');
        expect(groups.map((g) => g.key)).toEqual(['active', 'recent', 'rest']);
        expect(groups[0]!.items.map((i) => i.id)).toEqual(['a2', 'a1']);
        expect(groups[1]!.items.map((i) => i.id)).toEqual(['f', 'e', 'd', 'c', 'b']);
        expect(groups[2]!.items.map((i) => i.id)).toEqual(['y', 'z']);
        expect(groupItems(items, ' ZZZ ').flatMap((g) => g.items.map((i) => i.id))).toEqual(['z']);
        expect(groupItems(items, 'no such title')).toEqual([]);
    });

    it('hides when off, says nothing to choose when empty, and answers only a real id (skip is null)', () => {
        const items = [item('a1', 'x', 'active', '2026-01-01')];
        expect(rowVisible(null)).toBe(false);
        expect(rowVisible({ enabled: false, state: 'off', items })).toBe(false);
        expect(hasChoices({ enabled: true, state: 'unavailable', items: [] })).toBe(false);
        expect(hasChoices({ enabled: true, state: 'ok', items })).toBe(true);
        expect(storyAnswer('a1', items)).toBe('a1');
        expect(storyAnswer('', items)).toBeNull();
        expect(storyAnswer('gone', items)).toBeNull();
    });

    it('reads the 409 candidates and rides the local create body as story_ref only', () => {
        const body = { detail: { code: 'conflict', details: { candidates: [{ id: 'wi_feat1', title: 'Fixture Feature', kind: 'feature', score: 0.9 }, { nope: 1 }] } } };
        expect(candidatesOf(new ApiError('x', 409, 'conflict', body))).toEqual([{ id: 'wi_feat1', title: 'Fixture Feature', kind: 'feature' }]);
        expect(candidatesOf(new ApiError('x', 500, null, body))).toEqual([]);
        expect(candidatesOf(new Error('x'))).toEqual([]);
        expect(buildOpenProjectPayload('app', '/code/app', { story: 'wi_story1' }, {}).story_ref).toBe('wi_story1');
        expect(buildOpenProjectPayload('app', '/code/app', { story: null }, {})).not.toHaveProperty('story_ref');
        expect(buildOpenProjectPayload('app', 'ssh://studio/code/app', { story: 'wi_story1' }, {})).not.toHaveProperty('story_ref');
        expect(buildCreatePayload('app', '/code/app', null, { story: 'wi_story1' } as never, {}).story_ref).toBe('wi_story1');
        expect(buildCreatePayload('app', '/code/app', null, null, {})).not.toHaveProperty('story_ref');
    });
});
