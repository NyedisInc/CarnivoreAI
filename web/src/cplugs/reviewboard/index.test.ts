import { describe, expect, it } from 'vitest';
import { BUILTIN_CPLUGS } from '../builtin';
import { reviewboardCplug } from './index';

describe('reviewboard web plugin', () => {
    it('is on the web ship list, off by default, and mirrors the server manifest', () => {
        expect(BUILTIN_CPLUGS.map((c) => c.id)).toContain('reviewboard');
        expect(reviewboardCplug.manifest.id).toBe('reviewboard');
        expect(reviewboardCplug.manifest.default_enabled).toBe(false);
        expect(reviewboardCplug.manifest.requires).toEqual(['huddle']);
    });

    it('declares the boards folder setting and the board tools from the one manifest', () => {
        const manifest = reviewboardCplug.manifest as unknown as {
            settings_schema: { fields: Record<string, { kind: string }> };
            surfaces: { mcp_tools: string[]; topics: string[] };
        };
        expect(manifest.settings_schema.fields.boardsRoot!.kind).toBe('string');
        expect(manifest.surfaces.mcp_tools).toEqual([
            'task_manager_boards_list', 'task_manager_board_get', 'task_manager_board_create', 'task_manager_board_revision_add', 'task_manager_board_focus',
            'task_manager_scratch_post', 'task_manager_scratch_clear', 'task_manager_board_attachment_add', 'task_manager_board_attachment_remove',
            'task_manager_board_live_set', 'task_manager_board_milestone_add', 'task_manager_board_live_stop',
        ]);
        expect(manifest.surfaces.topics).toEqual(['boards', 'drafts']);
        expect(reviewboardCplug.tabs?.map((t) => t.id)).toEqual(['reviewboard']);
    });
});
