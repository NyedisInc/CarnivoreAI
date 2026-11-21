
export const ISSUE_URL = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+\/issues\/(\d+)$/;

export function issueNumber(url: string | null | undefined): string | null {
  return url?.match(ISSUE_URL)?.[1] ?? null;
}
