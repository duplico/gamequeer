init:
	uv sync --extra test

test:
	# --extra test (not just a bare `uv run pytest`) so this doesn't depend
	# on `make init` (or any other prior `uv sync`) having run first: `uv
	# run` only syncs base dependencies by default, and if `pytest` isn't
	# in the project's own .venv, command resolution silently falls through
	# to whatever `pytest` is on the rest of PATH (wrong version, wrong -
	# or no - gqc install) instead of erroring.
	uv run --extra test pytest tests

.PHONY: init test
