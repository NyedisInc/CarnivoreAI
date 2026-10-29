
from __future__ import annotations

import os
from typing import List, Tuple

from src.core.pack.transport import github_account, ladder

HELPER_KEY = "credential.https://github.com.helper"
INSTEAD_KEY = "url.https://github.com/.insteadOf"
INSTEAD_VALUE = "git@github.com:"


def helper_script(account: str, gh: str) -> str:
    if not github_account.valid_account(account):
        raise github_account.AccountError("bad_account", "that is not a GitHub account name")
    if not os.path.isabs(gh) or any(c in gh for c in "'\"`$;&|\n \\"):
        raise github_account.AccountError("gh_missing", "the gh path is not usable in a helper")
    return (f'!f() {{ test "$1" = get || exit 0; echo username={account}; '
            f'echo "password=$({gh} auth token --hostname github.com --user {account})"; }}; f')


def config_pairs(account: str, gh: str) -> List[Tuple[str, str]]:
    return [(HELPER_KEY, ""), (HELPER_KEY, helper_script(account, gh)), (INSTEAD_KEY, INSTEAD_VALUE)]


def install(repo: str, account: str, *, air_gap: bool) -> List[str]:
    if air_gap:
        raise ladder.AirGapViolation("air-gap: no GitHub credential helper is written for an air-gapped project")
    gh = github_account.gh_path()
    if gh is None:
        raise github_account.AccountError("gh_missing", "gh is not installed on this computer")
    pairs = config_pairs(account, gh)
    for index, (key, value) in enumerate(pairs):
        flag = "--replace-all" if index == 0 or key == INSTEAD_KEY else "--add"
        done = ladder.run(["git", "-C", repo, "config", "--local", flag, key, value], air_gap=False)
        if done.returncode != 0:
            raise RuntimeError("helper_install_failed")
    return [HELPER_KEY, INSTEAD_KEY]
