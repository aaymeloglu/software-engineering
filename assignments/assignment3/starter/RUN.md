# Assignment 3 — How to run

## Prerequisites

CPython 3.12, 3.13, or 3.14. The compiled modules are version-locked to CPython's bytecode format, so the shared conftest at `assignments/a3-testing/conftest.py` refuses to load under any other minor version and tells you which versions are supported.

If you need to install a supported version:

```
pyenv install 3.12
pyenv local 3.12
```

or with `uv`:

```
uv venv --python 3.12 .venv
source .venv/bin/activate
```

## Install pytest

From the class repo root:

```
pip install -r starter/assignment3/requirements.txt
```

## Write your tests

Your Phase 1 work lives at `assignments/a3-testing/<your-github-username>/phase1/`. Create it, add your three test files and your README:

```
assignments/a3-testing/<your-github-username>/phase1/
  tests/
    test_lru_cache.py
    test_interval_merger.py
    test_cart.py
  README.md
```

Each test file imports the opaque module by name:

```python
from lru_cache import LRUCache
from interval_merger import merge
from cart import Cart
```

You do not need your own conftest.py for Phase 1. A shared one at `assignments/a3-testing/conftest.py` handles the import path for every student.

## Run tests

From your phase1 directory:

```
cd assignments/a3-testing/<your-github-username>/phase1
pytest tests/ -v
```

With no environment variables set, the modules behave correctly per spec and your tests should all pass.

## The `BUGS` env var

There is a `BUGS` environment variable the grading harness uses to toggle seeded bugs on one at a time. You do not know the bug names, and you should not try to guess them. Write your tests from the spec. If you leave `BUGS` unset, the modules behave correctly, and that's the only configuration you need while writing your suite.

## Phase 1 submission

Commit your `phase1/` directory (your tests and your README) and tag:

```
git tag phase-1-submit-<your-github-username>
git push origin phase-1-submit-<your-github-username>
```

## Phase 2

After the Phase 1 deadline, the buggy source and bug catalog appear under `starter/assignment3/phase2/`. Copy the source files and the conftest template into your submission:

```
mkdir -p assignments/a3-testing/<you>/phase2/src
cp starter/assignment3/phase2/src/*.py assignments/a3-testing/<you>/phase2/src/
cp starter/assignment3/phase2/conftest_template.py assignments/a3-testing/<you>/phase2/conftest.py
cp -r assignments/a3-testing/<you>/phase1/tests assignments/a3-testing/<you>/phase2/tests
```

Then fix the source until every one of your tests passes. The phase2/conftest.py points pytest at your own `src/` so your tests exercise the code you're fixing instead of the starter's .pyc.

## Do not decompile

The `.pyc` files in `starter/assignment3/modules/` are intentionally opaque. Do not decompile them. The pedagogical point is to derive your tests from the spec without reading the implementation.
