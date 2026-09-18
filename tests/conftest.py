from copy import deepcopy

import pytest

from app.config import Settings
from app.models import Scenario
from scripts.run_public_cases import load_cases


@pytest.fixture
def case():
    return deepcopy(load_cases()[0])


@pytest.fixture
def scenario(case):
    return Scenario.model_validate(case["input"])


@pytest.fixture
def settings():
    return Settings(llm_api_key="test-placeholder", llm_model="mock-model")


def make_directive(kind="no_op", adjustment=None, index=0):
    return {
        "note_index": index,
        "applies": kind != "no_op",
        "directive_type": kind,
        "structured_adjustment": adjustment,
        "explanation": "Synthetic test directive.",
    }
