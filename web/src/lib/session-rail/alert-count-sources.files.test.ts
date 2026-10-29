import { describe, expect, test } from 'vitest';
import './alert-count-sources.svelte';
import { alertCountSource } from './alert-counts';

const scope = { sessionId: 'ses_files_count', rowId: 1, workingDir: '/x', projectId: 7 };

describe('files widget rail badge', () => {
  test('core.files publishes a count source, the one core.changes uses', () => {
    expect(alertCountSource('core.files')).toBeDefined();
    expect(alertCountSource('core.files')).toBe(alertCountSource('core.changes'));
  });
  test('no session or no read yet is unknown, never zero', () => {
    expect(alertCountSource('core.files')?.read(null)).toBeNull();
    expect(alertCountSource('core.files')?.read(scope)).toBeNull();
  });
  test('the read survives while another widget still holds the session', () => {
    const files = alertCountSource('core.files')!;
    const changes = alertCountSource('core.changes')!;
    const stopFiles = files.hold!(scope);
    const stopChanges = changes.hold!(scope);
    stopFiles();
    expect(changes.read(scope)).toBeNull();
    stopChanges();
  });
});
