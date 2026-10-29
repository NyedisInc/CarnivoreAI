
from __future__ import annotations

from src.models.catalog import ItemFrontMatter

REA_FM = {
    "description": "reverse engineer anything from your terminal or agent with one cli and mcp server",
    "author": "morluto",
    "author_url": "https://github.com/morluto",
    "homepage": "https://github.com/morluto/rea#readme",
    "repository": "https://github.com/morluto/rea",
}


def test_the_credit_fields_survive_the_model() -> None:
    fm = ItemFrontMatter.model_validate(REA_FM)
    assert (fm.author, fm.author_url, fm.homepage, fm.repository) == ("morluto", REA_FM["author_url"], REA_FM["homepage"], REA_FM["repository"])
    assert fm.model_dump(exclude_none=True) == REA_FM


def test_an_item_without_credit_still_parses_and_carries_none() -> None:
    fm = ItemFrontMatter.model_validate({"description": "says hello"})
    assert fm.author is None and fm.homepage is None
