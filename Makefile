# Local secrets (git-ignored); exported to every recipe.
-include .env
export

.PHONY: setup check test eval human human-extras strong-baseline serve demo demo-offline te-data te-collect te-evidence te serve-te deploy

setup:
	uv sync
	uv run python scripts/fetch_model.py

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run pyright

test:
	uv run pytest -q

# Offline by design: replays data/cache.sqlite, no key or network needed.
eval:
	PRAMAAN_OFFLINE=1 uv run python -m eval.run_eval
	PRAMAAN_OFFLINE=1 uv run python -m eval.run_eval --fresh
	PRAMAAN_OFFLINE=1 uv run python -m eval.run_eval --fresh2
	PRAMAAN_OFFLINE=1 uv run python -m eval.run_eval --te
	PRAMAAN_OFFLINE=1 uv run python -m eval.analysis

# Human recordings from /record.html: run the models once, then score on the frozen policy.
human:
	uv run python scripts/collect.py --manifest data/human/manifest.jsonl --concurrency 3
	PRAMAAN_OFFLINE=1 uv run python scripts/build_evidence.py --manifest data/human/manifest.jsonl --out data/human/evidence.jsonl
	PRAMAAN_OFFLINE=1 uv run python -m eval.run_eval --human

# PIN and account lines and spoken answers from /record.html. Separate from the locked set above.
human-extras:
	uv run python -m scripts.measure_extras $(EXTRAS_ARGS)

# Spends API credits on the first run; later runs replay data/cache.strong.sqlite.
strong-baseline:
	uv run python -m scripts.strong_baseline collect
	PRAMAAN_OFFLINE=1 uv run python -m scripts.strong_baseline score

# Telugu. PRAMAAN_LANG picks the recogniser settings and the acoustic model; responses go to their own cache.
TE = PRAMAAN_LANG=te PRAMAAN_CACHE=data/te/cache.sqlite

# Spends API credits: synthesises the Telugu clips.
te-data:
	uv run python scripts/fetch_model.py te
	uv run python scripts/gen_te.py

# Spends API credits on the first run: the agent and every recogniser over the Telugu clips.
te-collect:
	$(TE) uv run python scripts/collect.py --manifest data/te/manifest.jsonl --concurrency 6 $(TE_ARGS)

# Offline once collected: needs only the Telugu acoustic model.
te-evidence:
	$(TE) PRAMAAN_OFFLINE=1 uv run python scripts/build_evidence.py --manifest data/te/manifest.jsonl --out data/te/evidence.jsonl

# Offline: Telugu test speakers on the policy frozen on Hindi.
te:
	PRAMAAN_OFFLINE=1 uv run python -m eval.run_eval --te

# The live demo in Telugu, beside the Hindi one: Telugu recognisers, acoustic model, questions and calls.
serve-te:
	cp data/te/cache.sqlite data/te/cache.live.sqlite
	PRAMAAN_LANG=te PRAMAAN_CACHE=data/te/cache.live.sqlite uv run uvicorn pramaan.live.server:app --host 127.0.0.1 --port 8766

# Publishes both hosted demos (Vercel projects pramaan-voice and pramaan-voice-te). main.py keeps them in
# replay mode even if the project holds keys.
deploy:
	vercel link --yes --project pramaan-voice && vercel deploy --prod --yes
	vercel link --yes --project pramaan-voice-te && vercel deploy --prod --yes -e PRAMAAN_LANG=te

PORT ?= 8765

# Live calls write to a throwaway copy: the committed cache is the evidence behind `make eval`.
serve:
	cp data/cache.sqlite data/cache.live.sqlite
	PRAMAAN_CACHE=data/cache.live.sqlite uv run uvicorn pramaan.live.server:app --host 127.0.0.1 --port $(PORT)

demo:
	uv run python scripts/selfcheck.py && $(MAKE) serve

# No network and no keys: recorded calls only, the model's answers and every recogniser come from the cache.
demo-offline:
	PRAMAAN_OFFLINE=1 uv run uvicorn pramaan.live.server:app --host 127.0.0.1 --port $(PORT)

