import pytest
from pathlib import Path

TEST_DATA = Path(__file__).parent.parent / "test_data"


def pytest_configure(config):
    config.addinivalue_line("markers", "needs_test_data: requires test_data/ directory")


@pytest.fixture
def test_data_dir():
    if not TEST_DATA.exists() or not any(TEST_DATA.iterdir()):
        pytest.skip("test_data/ not available")
    return TEST_DATA
