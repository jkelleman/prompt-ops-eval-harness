import pytest

from eval_harness import (
    AgenticIntentCompiler,
    LakehouseCatalogResolver,
    SAMPLE_CATALOG,
    SelfHealingInterceptor,
    SimulatedLakehouseRuntime,
)


@pytest.fixture
def resolver():
    return LakehouseCatalogResolver(SAMPLE_CATALOG)


@pytest.fixture
def compiler(resolver):
    return AgenticIntentCompiler(resolver)


@pytest.fixture
def runtime(resolver):
    return SimulatedLakehouseRuntime(resolver, SelfHealingInterceptor(resolver))
