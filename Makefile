# Local secrets (git-ignored); exported to every recipe.
-include .env
export

.PHONY: setup check test eval human human-extras strong-baseline digits-data digits serve demo demo-offline demo-offline-te play te-data te-collect te-evidence te serve-te deploy

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
	PAKKA_OFFLINE=1 uv run python -m eval.run_eval
	PAKKA_OFFLINE=1 uv run python -m eval.run_eval --fresh
	PAKKA_OFFLINE=1 uv run python -m eval.run_eval --fresh2
	PAKKA_OFFLINE=1 uv run python -m eval.run_eval --te
	PAKKA_OFFLINE=1 uv run python -m eval.analysis

# Human recordings from /record.html: run the models once, then score on the frozen policy.
human:
	uv run python scripts/collect.py --manifest data/human/manifest.jsonl --concurrency 3
	PAKKA_OFFLINE=1 uv run python scripts/build_evidence.py --manifest data/human/manifest.jsonl --out data/human/evidence.jsonl
	PAKKA_OFFLINE=1 uv run python -m eval.run_eval --human

# PIN and account lines and spoken answers from /record.html. Separate from the locked set above.
human-extras:
	uv run python -m scripts.measure_extras $(EXTRAS_ARGS)

# Spends API credits on the first run; later runs replay data/cache.strong.sqlite.
strong-baseline:
	uv run python -m scripts.strong_baseline collect
	PAKKA_OFFLINE=1 uv run python -m scripts.strong_baseline score

# PIN codes and account numbers on the test speakers. Its own cache, so the evidence behind `make eval` cannot move.
DIGITS = PAKKA_CACHE=data/digits/cache.sqlite PAKKA_EXTRAS_CACHE=data/digits/cache.sqlite

# Spends API credits: synthesises the clips.
digits-data:
	uv run python scripts/gen_digits.py

# Spends API credits on the first run; later runs replay data/digits/cache.sqlite (the clips are still needed).
digits:
	$(DIGITS) uv run python -m scripts.measure_extras --manifest data/digits/manifest.jsonl --out results/digits.json --concurrency 6

# Telugu. PAKKA_LANG picks the recogniser settings and the acoustic model; responses go to their own cache.
TE = PAKKA_LANG=te PAKKA_CACHE=data/te/cache.sqlite

# Spends API credits: synthesises the Telugu clips.
te-data:
	uv run python scripts/fetch_model.py te
	uv run python scripts/gen_te.py

# Spends API credits on the first run: the agent and every recogniser over the Telugu clips.
te-collect:
	$(TE) uv run python scripts/collect.py --manifest data/te/manifest.jsonl --concurrency 6 $(TE_ARGS)

# Offline once collected: needs only the Telugu acoustic model.
te-evidence:
	$(TE) PAKKA_OFFLINE=1 uv run python scripts/build_evidence.py --manifest data/te/manifest.jsonl --out data/te/evidence.jsonl

# Offline: Telugu test speakers on the policy frozen on Hindi.
te:
	PAKKA_OFFLINE=1 uv run python -m eval.run_eval --te

# The live demo in Telugu, beside the Hindi one: Telugu recognisers, acoustic model, questions and calls.
serve-te:
	cp data/te/cache.sqlite data/te/cache.live.sqlite
	PAKKA_LANG=te PAKKA_CACHE=data/te/cache.live.sqlite uv run uvicorn pakka.live.server:app --host 127.0.0.1 --port 8766

# Publishes both hosted demos (Vercel projects pakka and pakka-te). They are live only while
# the project sets PAKKA_HOSTED_LIVE=1; without it main.py serves replay mode whatever keys are present.
deploy:
	vercel link --yes --project pakka && vercel deploy --prod --yes
	vercel link --yes --project pakka-te && vercel deploy --prod --yes -e PAKKA_LANG=te

PORT ?= 8765

# Live calls write to a throwaway copy: the committed cache is the evidence behind `make eval`.
serve:
	cp data/cache.sqlite data/cache.live.sqlite
	PAKKA_CACHE=data/cache.live.sqlite uv run uvicorn pakka.live.server:app --host 127.0.0.1 --port $(PORT)

demo:
	uv run python scripts/selfcheck.py && $(MAKE) serve

# No network and no keys: recorded calls only, the model's answers and every recogniser come from the cache.
demo-offline:
	PAKKA_OFFLINE=1 uv run uvicorn pakka.live.server:app --host 127.0.0.1 --port $(PORT)

# The same in Telugu, on port 8766. Downloads the Telugu acoustic model (481 MB) on the first run.
demo-offline-te:
	uv run python scripts/fetch_model.py te
	PAKKA_OFFLINE=1 $(TE) uv run uvicorn pakka.live.server:app --host 127.0.0.1 --port 8766

# Plays recorded calls against a running server and prints both sides: `make play`, `make play CALL=one_question`,
# `make play PORT=8766` for the Telugu server.
play:
	uv run python scripts/play_call.py $(CALL) --url http://127.0.0.1:$(PORT)

