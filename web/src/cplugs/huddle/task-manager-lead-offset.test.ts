import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

const src = (name: string): string => readFileSync(`src/cplugs/huddle/${name}`, 'utf8');
const PULL = /margin-left:\s*calc\(-1 \* var\(--hdr-lead, 0px\)\)/;

describe('the lead offset', () => {
  test('the row derives it from its grid variables, never a pixel offset', () => {
    expect(src('TaskManagerRow.svelte')).toMatch(/--hdr-lead:\s*calc\(var\(--_check-w\) \+ var\(--_mark-w\) \+ 2 \* var\(--_col-gap\)\)/);
  });

  test.each([
    ['TaskManagerRowPosts.svelte', /\.tkm-posts \{[^}]*margin: 0 0 0 calc\(-1 \* var\(--hdr-lead, 0px\)\)/],
    ['TaskManagerRowPosts.svelte', new RegExp(`\\.tkm-question-reply \\{[^}]*${PULL.source}`)],
    ['TaskManagerRow.svelte', new RegExp(`\\.tkm-reply \\{[^}]*${PULL.source}`)],
    ['HuddleThread.svelte', new RegExp(`\\.hdt-reply \\{[^}]*${PULL.source}`)],
    ['HuddleThread.svelte', new RegExp(`\\.hdt-box \\{[^}]*${PULL.source}`)],
  ])('%s pulls back by the lead', (file, re) => {
    expect(src(file)).toMatch(re);
  });

  test('a narrow row zeroes the lead on the peek, the reply and the detail', () => {
    expect(src('TaskManagerRowPeek.svelte')).toMatch(/@container hdr \(max-width: 22rem\) \{[^]*?--hdr-lead: 0px/);
    expect(src('TaskManagerRow.svelte')).toMatch(/\.tkm-detail,\s*\.tkm-reply \{\s*--hdr-lead: 0px/);
  });

  test('the review card pulls back and a narrow row zeroes it', () => {
    expect(src('HuddleReview.svelte')).toMatch(new RegExp(`:global\\(\\.hdr > \\.tkm-review\\) \\{[^}]*${PULL.source}`));
    expect(src('HuddleReview.svelte')).toMatch(/@container hdr \(max-width: 22rem\) \{[^]*?margin-left: 0/);
  });

  test('one shared rule gives every card under the detail and the peek the lead', () => {
    expect(src('TaskManagerRow.svelte')).toMatch(new RegExp(`:global\\(\\.tkm-lead-host > :not\\([^)]*\\)\\) \\{[^}]*${PULL.source}`));
    expect(src('TaskManagerRow.svelte')).toMatch(/class="tkm-detail tkm-lead-host"/);
    expect(src('TaskManagerRowPeek.svelte')).toMatch(/class="tkm-peek tkm-lead-host"/);
  });

  test('question forms and artifact cards ride inside a bubble list that already pulls back, never twice', () => {
    expect(src('TaskManagerRow.svelte')).toMatch(/:not\(\.tkm-posts, \.hdt,/);
    expect(src('TaskManagerRowPosts.svelte')).toMatch(/<TaskManagerAsk \{message\}/);
    expect(src('TaskManagerRowPosts.svelte')).toMatch(/<TaskManagerArtifactCard/);
  });
});
