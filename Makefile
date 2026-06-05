.PHONY: install run test eval mock mobile clean fmt

VENV=.venv
PY=$(VENV)/bin/python
PIP=$(VENV)/bin/pip

install:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run:
	AI_MODE=auto $(PY) -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

test:
	AI_MODE=mock $(PY) -m pytest

mock:
	$(PY) -m mock.make_mock_video --frames 60

eval: mock
	AI_MODE=mock $(PY) -m eval.evaluate

mobile:
	cd mobile && npm install && npx expo start

clean:
	rm -rf $(VENV) **/__pycache__ .pytest_cache events.sqlite3 mock/sample_frames mock/*.mp4 runs
