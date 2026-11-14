.PHONY: install run mock test smoke clips e2e deploy

PORT ?= 8080

install:
	uv sync

run:
	uv run uvicorn server.main:app --host 0.0.0.0 --port $(PORT)

mock:
	VOUCH_MOCK=1 uv run uvicorn server.main:app --host 0.0.0.0 --port $(PORT)

test:
	uv run pytest -q

smoke:
	uv run python scripts/audio_smoke.py

clips:
	uv run python scripts/generate_clips.py

e2e:
	uv run pytest tests/test_hero_e2e.py -v

deploy:
	bash scripts/deploy.sh
