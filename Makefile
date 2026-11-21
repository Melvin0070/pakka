# Local secrets (git-ignored); exported to every recipe.
-include .env
export

.PHONY: setup check test eval human serve demo demo-offline model

setup:
	uv sync
	uv run python scripts/fetch_model.py

check:
	uv run ruff check src tests eval scripts
	uv run ruff format --check src tests eval scripts
	uv run pyright

test:
	uv run pytest -q

# Offline by design: replays data/cache.sqlite, no key or network needed.
eval:
	PRAMAAN_OFFLINE=1 uv run python -m eval.run_eval
	PRAMAAN_OFFLINE=1 uv run python -m eval.run_eval --fresh
	PRAMAAN_OFFLINE=1 uv run python -m eval.analysis

# Human recordings from /record.html: run the models once, then score on the frozen policy.
human:
	uv run python scripts/collect.py --manifest data/human/manifest.jsonl --concurrency 3
	uv run python scripts/build_evidence.py --manifest data/human/manifest.jsonl --out data/human/evidence.jsonl
	PRAMAAN_OFFLINE=1 uv run python -m eval.run_eval --human

serve:
	uv run uvicorn pramaan.live.server:app --host 127.0.0.1 --port 8765

demo:
	uv run python scripts/selfcheck.py && $(MAKE) serve

# No network and no keys: recorded calls only, the model's answers and every recogniser come from the cache.
demo-offline:
	PRAMAAN_OFFLINE=1 uv run uvicorn pramaan.live.server:app --host 127.0.0.1 --port 8765
