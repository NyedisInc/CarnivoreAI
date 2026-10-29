
from src.core.message_model_secrets import scan_text


def _jwt() -> str:
    return ".".join(["eyJ" + "hbGciOiJIUzI1NiJ9", "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ", "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"])


def test_bearer_plus_jwt_is_one_finding() -> None:
    found = scan_text("Authorization: Bearer " + _jwt())
    assert len(found) == 1


def test_bearer_plus_github_token_is_one_finding() -> None:
    found = scan_text("Bearer " + "gh" + "p_" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bD1fH3jL5")
    assert [f.detector for f in found] == ["github_token"]
