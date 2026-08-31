CONDA_RUN = $(HOME)/miniforge3/bin/conda run -n pravaah --no-capture-output

.PHONY: check preflight fakes serve ui-dev streamlit clean-outputs radar advisories

check:                       ## Phase 0 gate: every library imports
	$(CONDA_RUN) python scripts/env_check.py

preflight:                   ## RUN THIS BEFORE PRESENTING - 13 gates
	$(CONDA_RUN) python scripts/preflight.py

radar:                       ## publish newly logged IMD radar frames
	$(CONDA_RUN) python scripts/publish_radar.py

advisories:                  ## regenerate the cached bilingual advisories
	$(CONDA_RUN) python scripts/generate_advisories.py

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
