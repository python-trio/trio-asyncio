import pytest
from . import TestConfig

@pytest.fixture
def config():
    return TestConfig()

