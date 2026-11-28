
from __future__ import annotations

import pytest

from src.plugins.host import sideload, sideload_copy

DATALESS = 0x40000000


def test_placeholder_is_a_stub_name_or_the_dataless_flag():
    assert sideload_copy.is_placeholder(".main.py.icloud", 0)
    assert sideload_copy.is_placeholder("main.py", DATALESS)
    assert not sideload_copy.is_placeholder("main.py", 0)
    assert not sideload_copy.is_placeholder(".hidden.icloud.txt", 0)


def test_copy_tree_refuses_a_stub_and_names_the_fix(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "carnivore.toml").write_text('[plugin]\nid = "x"\n')
    (src / ".main.py.icloud").write_text("stub")
    with pytest.raises(sideload.SideloadRefused) as caught:
        sideload_copy.copy_tree(src, tmp_path / "dest")
    assert caught.value.code == "source_not_downloaded" and "download the folder first" in str(caught.value)


def test_copy_tree_still_copies_a_normal_folder(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("print(1)\n")
    assert list(sideload_copy.copy_tree(src, tmp_path / "dest")) == ["main.py"]
