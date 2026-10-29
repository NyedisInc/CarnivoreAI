
from src.models import CloneProjectRequest


def test_parent_dir_defaults_to_none_so_the_route_uses_the_configured_projects_folder() -> None:
    assert CloneProjectRequest(repo_url="owner/repo").parent_dir is None


def test_an_explicit_parent_dir_is_kept() -> None:
    assert CloneProjectRequest(repo_url="owner/repo", parent_dir="/tmp/x").parent_dir == "/tmp/x"
