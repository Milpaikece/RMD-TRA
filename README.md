# RMD-TRA — A Multi-Agent Thesis Auditor That Cannot Hallucinate Its Numbers

**Eight Gemini sub-agents + a deterministic Python verification layer that recomputes every critical figure — validated on real transportation-engineering theses.**

**Stack:** Google Agent Development Kit (ADK) 2.0 · Gemini 2.5 Flash (Vertex AI) · FastAPI
**Context:** Capstone — *5-Day AI Agents Intensive Vibe Coding Course with Google* (Kaggle)
**Author:** Rudy Max — Head of Transportation Study Program, ITL Trisakti

---

## What it does

Upload a full undergraduate thesis (`.docx` / `.pdf`) and RMD-TRA returns a **publication-quality Word audit report** in ~3 minutes: a chapter-to-chapter consistency check, a research-question answer matrix (Findings → Discussion → Conclusion), deterministic verification of every key number, plagiarism-risk paraphrasing, a Scopus-ready draft, and a thesis-defense question simulation.

Its founding principle, set by a real program head who evaluates real student work: **every claim must be provable against the source document, and every critical number is recomputed by Python — never guessed by the LLM.**

## Why it's different — the anti-hallucination layer

Before any LLM sees the text, a deterministic Python layer runs and injects *proven* numbers into the agents' prompts:

- **`app/pillar5/finance_tools.py`** — column-aware extraction + recomputation of **NPV, IRR (binary search), BCR, payback** from cash-flow tables.
- **`app/pillar5/survey_tools.py`** — recomputes the **Slovin sample-size formula** `n = N / (1 + N·e²)`, checks percentage sums, re-derives ratio claims.

The system auto-detects the thesis family (financial-feasibility vs. survey/service-quality) and shows only the relevant verifier. Whole classes of numeric error become impossible to miss because the math happens *outside* the language model.

## The 8 sub-agents (ADK `ParallelAgent` + `SequentialAgent`)

Consistency Engine · Statistical & Methodology Auditor · Discussion Critique · Ghost-Citation Detector · Paraphrasing Engine · Journal/IMRAD Drafter · Auto-Template Converter · Exam-Defense Simulation.

---

## Prerequisites

- Python **3.11+**
- [`uv`](https://docs.astral.sh/uv/) package manager
- Google Cloud SDK (`gcloud`) with a project that has **Vertex AI API** enabled and billing active

## Local setup

```bash
# 1. Clone
git clone <repo-url> && cd rmd-tra

# 2. Install uv (if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh      # Windows: use the PowerShell installer

# 3. Create the venv and install dependencies
uv sync

# 4. Configure environment — create a .env file in the project root:
cat > .env <<'EOF'
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-east4
EOF

# 5. Authenticate (Application Default Credentials)
gcloud auth application-default login
gcloud config set project your-gcp-project-id

# 6. Run the server
uv run uvicorn app.fast_api_app:app --host 127.0.0.1 --port 8080
```

Open **http://localhost:8080** and upload a thesis.

> **Tip:** avoid `--reload` while running an analysis — a reload can leave a zombie process holding port 8080. If a start fails with *"Access is denied"* on `.venv`, a previous server is still running: free the port first
> (`Get-NetTCPConnection -LocalPort 8080 | %{ Stop-Process -Id $_.OwningProcess -Force }` on Windows), then start again.

## Run the tests

```bash
uv run pytest tests/ -q     # 25 self-contained regression tests
```

---

## How to use (API)

`POST /analyze` with JSON:

```bash
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "thesis_text": "<full extracted thesis text>",
    "thesis_title": "Analisis Kelayakan ...",
    "student_name": "Nama Mahasiswa"
  }'
```

Response includes the combined 8-agent `audit_text` and the generated report as `docx_base64`. The web UI at `/` does extraction (`.docx`/`.pdf`) and download for you.

## Project structure

```
rmd-tra/
├── app/
│   ├── fast_api_app.py          # FastAPI app; extraction, verification gates, /analyze
│   └── pillar5/
│       ├── agents.py            # 8 sub-agents + orchestrator (ADK)
│       ├── finance_tools.py     # deterministic NPV/IRR/BCR/payback recompute
│       ├── survey_tools.py      # deterministic Slovin / % / ratio checks
│       └── word_exporter.py     # Word report (tables, OMML math, matrix)
├── static/index.html            # web frontend
├── tests/test_extraction.py     # 25 regression tests
├── pyproject.toml
└── README.md
```

## Deploy (optional, Cloud Run)

```bash
gcloud run deploy rmd-tra \
  --source . --region us-east4 --port 8080 \
  --memory 2Gi --timeout 1200 --allow-unauthenticated \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=your-gcp-project-id,GOOGLE_CLOUD_LOCATION=us-east4"
```

A live demo requires Vertex AI credentials; for judges without GCP access, the accompanying **video** demonstrates the full workflow end-to-end.

---

## Validated on real theses

- **Financial thesis** (electric-bus feasibility): NPV recomputed for both fleets from cash-flow tables; a false-positive from an earlier LLM-only version was eliminated by column-aware attribution.
- **Survey thesis** (train-station service quality): the Slovin check caught a real contradiction — a stated 5% margin of error whose sample of 100 (population 28,554) actually implies **10%** — which the LLM then expanded into a full, cross-referenced critique.

---

*Built for the 5-Day AI Agents Intensive Vibe Coding Course with Google (Kaggle Capstone).*
