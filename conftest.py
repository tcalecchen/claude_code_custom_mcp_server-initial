"""Present so pytest prepends the repo root to sys.path.

With pytest's default "prepend" import mode, the directory inserted into
sys.path is the test file's first non-package parent - i.e. `tests/`, which
would leave `import server` unresolvable. A root-level conftest.py makes
pytest insert the repo root as well. Intentionally empty otherwise.
"""
