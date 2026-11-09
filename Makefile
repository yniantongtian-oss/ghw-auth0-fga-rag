.PHONY: test serve demo

test:
	pytest -q

serve:
	uvicorn app.main:app --host 0.0.0.0 --port 8000

demo:
	python -m app.demo
