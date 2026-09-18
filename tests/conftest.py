import pytest

from anton.config import Settings
from anton.store import Store


@pytest.fixture
def db(tmp_path):
    return Store(
        str(tmp_path / "anton.db"),
        Settings(
            run_id="run-1",
            deployed_sha="a" * 40,
            seed_regression_sha="a" * 40,
            known_good_sha="b" * 40,
        ),
    )
