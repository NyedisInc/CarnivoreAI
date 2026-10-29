import subprocess

from src.core.pack.migrate import code
from src.core.pack.transport import bundles

SENDER = "iid-home"
ORIGIN = "git@github.com:o/r.git"


def _g(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True, text=True).stdout.strip()


def _home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    _g(home, "init", "-q", "-b", "trunk")
    (home / "a.txt").write_text("1")
    _g(home, "add", "a.txt")
    _g(home, "commit", "-q", "-m", "one")
    _g(home, "remote", "add", "origin", ORIGIN)
    return home


def _carry(tmp_path, home, air_gap):
    replica = tmp_path / "replica"
    replica.mkdir()
    bundle = str(tmp_path / "x.bundle")
    assert bundles.make_bundle(str(home), bundle, known_tips=[], air_gap=air_gap)
    bundles.apply_bundle(str(replica), bundle, SENDER, air_gap=air_gap)
    return replica


def test_replica_gets_checkout_and_origin(tmp_path):
    home = _home(tmp_path)
    replica = _carry(tmp_path, home, False)
    assert code.checkout_replica(str(replica), SENDER, bundles.current_branch(str(home)), bundles.origin_url(str(home)), air_gap=False)
    assert (replica / "a.txt").read_text() == "1"
    assert bundles.current_branch(str(replica)) == "trunk"
    assert bundles.origin_url(str(replica)) == "https://github.com/o/r.git"
    assert not code.checkout_replica(str(replica), SENDER, "trunk", ORIGIN, air_gap=False)


def test_air_gapped_replica_checks_out_with_no_origin(tmp_path):
    home = _home(tmp_path)
    replica = _carry(tmp_path, home, True)
    assert code.checkout_replica(str(replica), SENDER, "trunk", ORIGIN, air_gap=True)
    assert (replica / "a.txt").exists()
    assert bundles.origin_url(str(replica)) is None


def test_replica_with_own_commits_still_gets_origin(tmp_path):
    home = _home(tmp_path)
    replica = _carry(tmp_path, home, False)
    assert code.checkout_replica(str(replica), SENDER, "trunk", None, air_gap=False)
    assert bundles.origin_url(str(replica)) is None
    assert not code.checkout_replica(str(replica), SENDER, "trunk", ORIGIN, air_gap=False)
    assert bundles.origin_url(str(replica)) == "https://github.com/o/r.git"
