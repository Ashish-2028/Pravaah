CONDA_RUN = $(HOME)/miniforge3/bin/conda run -n pravaah --no-capture-output

.PHONY: check fakes serve ui-dev streamlit clean-outputs

check:                       ## Phase 0 gate: every library imports
	$(CONDA_RUN) python scripts/env_check.py

fakes:                       ## P1-T5: regenerate contract-shaped fake outputs
	$(CONDA_RUN) python scripts/make_fakes.py

serve:                       ## FastAPI (serves data/outputs/ + built UI)
	$(CONDA_RUN) uvicorn serve.main:app --reload --port 8000

streamlit:                   ## validation harness / fallback demo
	$(CONDA_RUN) streamlit run ui-fallback/streamlit_app.py

ui-dev:                      ## Vite dev server (proxies /api -> :8000)
	cd ui && npm run dev

clean-outputs:
	rm -rf data/outputs/*/
