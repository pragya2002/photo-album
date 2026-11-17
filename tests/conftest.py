import importlib.util
import os
import pathlib

import pytest

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("OPENSEARCH_ENDPOINT", "https://search-photos-test.us-east-1.es.amazonaws.com")
os.environ.setdefault("LEX_BOT_ID", "TESTBOTID")

ROOT = pathlib.Path(__file__).resolve().parents[1] / "lambdas"


def _load(name, folder):
    spec = importlib.util.spec_from_file_location(name, ROOT / folder / "lambda_function.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def lf1():
    return _load("lf1", "index-photos")


@pytest.fixture(scope="session")
def lf2():
    return _load("lf2", "search-photos")
