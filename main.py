from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from typing import Dict
from datetime import datetime
import uuid
import csv
import httpx
import json
from langchain_community.vectorstores import FAISS
from langchain_ollama.embeddings import OllamaEmbeddings
from langchain_core.documents import Document
import re

app = FastAPI(title="GreenPack EPR Compliance API")

declarations_db: Dict[str, dict] = {}

class DeclaredQuantities(BaseModel):
    rigid_plastic: float = Field(..., ge=0, description="Weight of rigid plastic in kg")
    flexible_plastic: float = Field(..., ge=0, description="Weight of flexible plastic in kg")
    multilayer_plastic: float = Field(..., ge=0, description="Weight of multilayer plastic in kg")

class DeclarationRequest(BaseModel):
    producer_id: str = Field(..., min_length=1)
    month: str = Field(..., description="Format: YYYY-MM")
    declared_quantities_kg: DeclaredQuantities

    @field_validator('month')
    @classmethod
    def validate_month_format(cls, v: str) -> str:
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v):
            raise ValueError('Month must be in YYYY-MM format (e.g., 2026-04)')
        return v

class AskRequest(BaseModel):
    question: str = Field(..., min_length=2)


@app.post("/submit")
async def submit_declaration(payload: DeclarationRequest):
    
    record_id = f"REC-{uuid.uuid4().hex[:8].upper()}"
    timestamp = datetime.utcnow().isoformat()
    
    record = {
        "record_id": record_id,
        "timestamp": timestamp,
        "producer_id": payload.producer_id,
        "month": payload.month,
        "declared_quantities_kg": payload.declared_quantities_kg.model_dump()
    }
    
    declarations_db[record_id] = record
    
    return record


def get_erp_data(producer_id: str, month: str) -> dict:
    erp_records = {}
    try:
        with open("erp_data.csv", mode="r") as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row["producer_id"] == producer_id and row["month"] == month:
                    erp_records[row["category"]] = float(row["procured_kg"])
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="erp_data.csv file not found on server")
    return erp_records


def get_declaration_for_period(producer_id: str, month: str) -> dict:
    for record in declarations_db.values():
        if record["producer_id"] == producer_id and record["month"] == month:
            return record["declared_quantities_kg"]

    raise HTTPException(status_code=404, detail="Declaration not found. Please submit first.")


def build_reconciliation(declaration: dict, erp_data: dict) -> tuple[dict, list[str]]:
    reconciliation = {}
    discrepancies = []

    for category, declared_val in declaration.items():
        procured_val = erp_data.get(category, 0)
        diff = declared_val - procured_val

        perc_diff = abs(diff) / procured_val if procured_val > 0 else 0
        is_flagged = perc_diff > 0.05

        reconciliation[category] = {
            "declared_kg": declared_val,
            "procured_kg": procured_val,
            "difference_kg": diff,
            "flagged": is_flagged,
        }

        if is_flagged:
            discrepancies.append(
                f"{category} (Declared: {declared_val}kg, Procured: {procured_val}kg)"
            )

    return reconciliation, discrepancies


async def generate_narrative(discrepancies: list[str]) -> str:
    prompt = f"""
    You are an EPR compliance auditor. Reconcile the plastic packaging data.
    Discrepancies found (>5% variance): {', '.join(discrepancies) if discrepancies else 'None'}
    
    Write a strict 3-5 sentence human-readable summary explaining these gaps in plain English and recommend a compliance action. Do not include introductory or concluding fluff.
    """

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "deepseek-r1:8b",
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=45.0,
            )
            return response.json().get("response", "Could not generate summary.").strip()
        except Exception as e:
            return f"Error connecting to local LLM: Make sure Ollama is running. Detail: {str(e)}"


@app.get("/summary/{producer_id}/{month}")
async def get_summary(producer_id: str, month: str):

    declaration = get_declaration_for_period(producer_id, month)

    erp_data = get_erp_data(producer_id, month)
    if not erp_data:
         raise HTTPException(status_code=404, detail="No ERP procurement data found for this period.")

    reconciliation, discrepancies = build_reconciliation(declaration, erp_data)
    llm_narrative = await generate_narrative(discrepancies)

    return {
        "reconciliation": reconciliation,
        "narrative": llm_narrative.strip()
    }


embeddings = OllamaEmbeddings(model="nomic-embed-text")

docs = []
try:
    with open("epr_documents.json", "r") as f:
        raw_docs = json.load(f)
        for d in raw_docs:
            doc = Document(
                page_content=d["content"], 
                metadata={"title": d["title"], "section": d["section"]}
            )
            docs.append(doc)
            
    vector_store = FAISS.from_documents(docs, embeddings)
    retriever = vector_store.as_retriever(search_kwargs={"k": 2})
except FileNotFoundError:
    print("Warning: epr_documents.json not found. Endpoint 3 will fail.")


@app.post("/ask")
async def ask_question(payload: AskRequest):
    
    retrieved_docs = retriever.invoke(payload.question)
    
    if not retrieved_docs:
        return {"answer": "I do not know based on the provided documents."}

    context_text = ""
    citations = []
    
    for i, doc in enumerate(retrieved_docs):
        context_text += f"\nDocument {i+1}:\n{doc.page_content}\n"
        citations.append(f"{doc.metadata.get('title')} - {doc.metadata.get('section')}")

    prompt = f"""
    You are a strict compliance assistant. Answer the user's question using ONLY the provided context.
    If the context does not contain the answer, you must reply exactly with: "I do not know based on the provided documents".
    Do not add outside information. Do not invent rules.
    
    Context:
    {context_text}
    
    Question: {payload.question}
    """

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama3.1:8b",
                    "prompt": prompt,
                    "stream": False
                },
                timeout=45.0
            )
            llm_answer = response.json().get("response", "Could not generate answer.")
        except Exception as e:
            llm_answer = f"Error connecting to local LLM: {str(e)}"

    
    if "I do not know" in llm_answer:
        citations = []

    return {
        "question": payload.question,
        "answer": llm_answer.strip(),
        "citations": citations
    }