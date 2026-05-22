# 🌿 GreenPack EPR Compliance API

> A production-ready AI-powered backend service for plastic packaging compliance — built for **GreenPack Industries** as part of the Innotechwise Junior AI Engineer screening task.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack & Choices](#tech-stack--choices)
- [Project Structure](#project-structure)
- [Setup & Installation](#setup--installation)
- [API Endpoints](#api-endpoints)
- [Sample Data Files](#sample-data-files)
- [RAG Corpus Sources](#rag-corpus-sources)
- [Demo: Running All Three Endpoints](#demo-running-all-three-endpoints)
- [AI Coding Assistant Usage](#ai-coding-assistant-usage)
- [Trade-offs & What I'd Do Differently](#trade-offs--what-id-do-differently)

---

## Overview

GreenPack Industries is a plastic packaging producer required to comply with India's **Extended Producer Responsibility (EPR)** regulations. Every month, they must:

1. Declare the quantity of plastic they've put into the market
2. Reconcile that declaration against actual ERP procurement data
3. Get plain-English answers to compliance questions from their compliance officer

This service handles all three — with deterministic validation, LLM-powered narrative summaries, and a RAG pipeline grounded in real EPR policy documents.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    FastAPI Service                       │
│                                                          │
│  POST /submit          GET /summary        POST /ask     │
│  ┌──────────┐         ┌──────────────┐   ┌──────────┐    │
│  │ Pydantic │         │ ERP CSV Read │   │  FAISS   │    │
│  │Validation│         │ Reconcile    │   │ Retriever│    │
│  │ + Store  │         │ LLM Narrative│   │ + LLM    │    │
│  └──────────┘         └──────────────┘   └──────────┘    │
│       │                      │                 │         │
│  In-Memory Dict         Ollama (local)    Ollama (local) │
│  (declarations_db)      deepseek-r1:8b       llama3.1:8b │
└──────────────────────────────────────────────────────────┘
```

---

## Tech Stack & Choices

| Component | Choice | Reason |
|---|---|---|
| **Framework** | FastAPI | Async support, automatic OpenAPI docs, Pydantic integration |
| **LLM (Summary)** | `deepseek-r1` via Ollama | Strong reasoning for structured compliance narratives; free, local, no API cost |
| **LLM (RAG Q&A)** | `llama3:8b` via Ollama | Fast, instruction-following; handles strict "only answer from context" prompting well |
| **Embeddings** | `nomic-embed-text` via Ollama | High-quality open embeddings, runs locally, no external calls |
| **Vector Store** | FAISS (via LangChain) | Lightweight, no server needed, zero-infra for a screening task; trivially swappable |
| **Storage** | In-memory Python dict | Sufficient for this scope; no overhead, easy to swap to SQLite/Postgres later |
| **Validation** | Pydantic v2 | No LLM needed — validation is deterministic; Pydantic is the right tool |

> **Why local Ollama over hosted APIs?** The task explicitly noted Ollama as an acceptable workflow. Running everything locally means zero API spend, no keys to manage, and closer to a real enterprise setup where data sovereignty matters.

---

## Project Structure

```
greenpack-epr/
├── main.py                  # FastAPI app — all three endpoints
├── erp_data.csv             # Mock ERP procurement feed
├── epr_documents.json       # RAG corpus (5 EPR/plastic policy documents)
├── requirements.txt         # Python dependencies
└── README.md
```

---

## Setup & Installation

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) installed and running locally

### 1. Pull required models

```bash
ollama pull deepseek-r1
ollama pull llama3:8b
ollama pull nomic-embed-text
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```


### 3. Start the server

```bash
uvicorn main:app --reload
```

The API will be live at `http://localhost:8000`. Swagger docs available at `http://localhost:8000/docs`.

---

## API Endpoints

### `POST /submit` — Submit Monthly Declaration

Accepts GreenPack's plastic declaration for a given month. **No LLM involved** — validation is purely deterministic via Pydantic.

**Request:**
```json
{
  "producer_id": "GREENPACK-001",
  "month": "2026-04",
  "declared_quantities_kg": {
    "rigid_plastic": 12000,
    "flexible_plastic": 8500,
    "multilayer_plastic": 3200
  }
}
```

**Response:**
```json
{
  "record_id": "REC-A3F2B1C9",
  "timestamp": "2026-04-15T10:32:00.000000",
  "producer_id": "GREENPACK-001",
  "month": "2026-04",
  "declared_quantities_kg": {
    "rigid_plastic": 12000.0,
    "flexible_plastic": 8500.0,
    "multilayer_plastic": 3200.0
  }
}
```

**Validation rules:**
- All weight fields must be ≥ 0
- `month` must match `YYYY-MM` format
- `producer_id` must be non-empty

---

### `GET /summary/{producer_id}/{month}` — Reconciliation Summary

Reads the stored declaration, cross-references the mock ERP CSV, flags categories with >5% variance, and uses an LLM to generate a plain-English compliance narrative.

**Example:** `GET /summary/GREENPACK-001/2026-04`

**Response:**
```json
{
  "reconciliation": {
    "rigid_plastic": {
      "declared_kg": 12000.0,
      "procured_kg": 11800.0,
      "difference_kg": 200.0,
      "flagged": false
    },
    "flexible_plastic": {
      "declared_kg": 8500.0,
      "procured_kg": 9100.0,
      "difference_kg": -600.0,
      "flagged": true
    },
    "multilayer_plastic": {
      "declared_kg": 3200.0,
      "procured_kg": 3200.0,
      "difference_kg": 0.0,
      "flagged": false
    }
  },
  "narrative": "GreenPack's April 2026 declaration shows a significant discrepancy in flexible plastic, where declared quantities (8,500 kg) are 6.6% below the actual procured amount (9,100 kg), exceeding the 5% tolerance threshold. Rigid plastic and multilayer plastic are within acceptable variance. The compliance team should review the flexible plastic declaration, identify whether the gap stems from data entry error or unreported usage, and file a corrected submission before the monthly deadline."
}
```

---

### `POST /ask` — EPR Policy Q&A (RAG)

Lets the compliance officer ask plain-English questions about EPR rules. Answers are grounded exclusively in the loaded document corpus — no hallucination.

**Request:**
```json
{
  "question": "What is the penalty for non-compliance with EPR targets?"
}
```

**Response:**
```json
{
  "question": "What is the penalty for non-compliance with EPR targets?",
  "answer": "Under the EPR framework, producers who fail to meet their annual plastic waste collection targets may face penalties including suspension of their EPR registration and restrictions on further plastic packaging usage until compliance is demonstrated.",
  "citations": [
    "CPCB EPR Guidelines 2022 - Section 4: Obligations of Producers",
    "Plastic Waste Management Rules 2016 (Amended 2022) - Rule 9"
  ]
}
```

If the corpus doesn't contain the answer:
```json
{
  "question": "...",
  "answer": "I do not know based on the provided documents.",
  "citations": []
}
```

---

## Sample Data Files

### `erp_data.csv`

Mock ERP procurement data for GREENPACK-001:

```csv
producer_id,month,category,procured_kg
GREENPACK-001,2026-04,rigid_plastic,11800
GREENPACK-001,2026-04,flexible_plastic,9100
GREENPACK-001,2026-04,multilayer_plastic,3200
```

### `epr_documents.json`

Five EPR policy documents used to seed the RAG vector store. Format:

```json
[
  {
    "id": "doc1",
    "title": "CPCB Notification 2022",
    "section": "Section 4.1",
    "content": "Producers of plastic packaging must recycle at least 50% of their rigid plastic waste by 2026..."
  },
  {
    "id": "doc2",
    "title": "GreenPack Compliance Handbook",
    "section": "Chapter 2",
    "content": "All monthly declarations must be submitted by the 15th. Failure to report accurate quantities results in a penalty of 5000 INR per day..."
  },
  {
    "id": "doc3",
    "title": "Plastic Waste Management Rules",
    "section": "Schedule II",
    "content": "Multilayer plastic producers must ensure 100% end-of-life disposal if recycling is not possible..."
  }
]
```

---

## RAG Corpus Sources

The three documents in `epr_documents.json` are fabricated mock policy documents written to simulate realistic EPR compliance content. They are clearly labeled as mock and are not sourced from live government publications.

| # | Title | Section | Content Summary |
|---|---|---|---|
| 1 | **CPCB Notification 2022** | Section 4.1 | Producers must recycle ≥50% of rigid plastic waste by 2026 |
| 2 | **GreenPack Compliance Handbook** | Chapter 2 | Declarations due by the 15th; ₹5,000/day penalty for inaccurate reporting |
| 3 | **Plastic Waste Management Rules** | Schedule II | 100% of multilayer plastic must go to end-of-life disposal if it cannot be recycled |

> All three documents are **fabricated mocks** for RAG demonstration purposes. The content is inspired by India's real EPR/PWM regulatory framework but should not be treated as legally accurate. For real compliance, refer to [CPCB EPR Guidelines](https://cpcb.nic.in) and the [Plastic Waste Management Rules 2016](https://egazette.gov.in).

---

## Demo: Running All Three Endpoints

Run these three `curl` commands in sequence to see the full workflow:

```bash
# Step 1: Submit a declaration
curl -s -X POST http://localhost:8000/submit \
  -H "Content-Type: application/json" \
  -d '{
    "producer_id": "GREENPACK-001",
    "month": "2026-04",
    "declared_quantities_kg": {
      "rigid_plastic": 12000,
      "flexible_plastic": 8500,
      "multilayer_plastic": 3200
    }
  }' | jq .

# Step 2: Get reconciliation summary (LLM-generated narrative)
curl -s http://localhost:8000/summary/GREENPACK-001/2026-04 | jq .

# Step 3: Ask a compliance question (RAG)
curl -s -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the EPR registration requirements for plastic producers?"}' | jq .
```

---

## AI Coding Assistant Usage

**Tool used: Claude (claude.ai) + Claude Code (terminal)**

Specific areas where AI assistance was used:

- **Endpoint 2 reconciliation logic** — Drafted the `get_erp_data` CSV reader and the percentage-diff flagging loop with Claude, then reviewed and tightened the edge case for `procured_val = 0`
- **LLM prompt engineering** — Iterated on the summary prompt to enforce "3-5 sentences, no fluff" and prevent the model from doing analysis instead of narration
- **RAG pipeline setup** — Used Claude Code to scaffold the FAISS + LangChain + Ollama embeddings wiring; caught that `OllamaEmbeddings` import path changed in recent LangChain versions
- **Pydantic v2 validators** — Got the `@field_validator` / `@classmethod` syntax right quickly with a prompt rather than reading migration docs

All AI-assisted sections were reviewed, understood, and adjusted before committing.

---

## Trade-offs & What I'd Do Differently

### Trade-off made: In-memory storage over SQLite

I chose a Python dict over SQLite to keep setup friction zero — no migrations, no file I/O errors, instant start. The trade-off is obvious: declarations don't survive a server restart. For a real system, I'd use SQLite (single file, no server, still trivial to set up) or Postgres if multi-instance deployment is needed.

### What I'd do with another day

**Swap Ollama models for the Anthropic API (Claude).** The deepseek-r1 and llama3 local models work, but Claude's instruction following on structured output tasks like "write exactly 3-5 sentences, no fluff" is noticeably more reliable. I'd also add:

- **Persistent storage** (SQLite with SQLAlchemy)
- **Auth middleware** — right now any caller can read any producer's data
- **Async ERP read** — the CSV read in Endpoint 2 is synchronous and would block under load
- **Streaming responses** on `/ask` for better UX on slow local models
- **Unit tests** for the reconciliation logic — the flagging math is the most business-critical piece and currently has no test coverage

---

*Built as part of the Innotechwise / Futuryntix Group Junior AI Engineer screening task.*
