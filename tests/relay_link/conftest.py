
import pytest

from tests.relay_link.support import OPEN_PHONES


@pytest.fixture(autouse=True)
def close_phones():
    yield
    while OPEN_PHONES:
        OPEN_PHONES.pop().close()
