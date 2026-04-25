# 🧠 AI WhatsApp + Web Chat Assistant (Hybrid RAG System)

## 📌 Overview

This project is a FastAPI-based backend for an AI-powered assistant that supports:

* WhatsApp chatbot (via webhook)
* Web chat widget (UUID-based users)
* Retrieval-Augmented Generation (RAG) for product-aware responses

The system combines:

* Conversation memory (PostgreSQL)
* Inventory retrieval (SQL + fuzzy + vector)
* LLM generation (Groq)

---

## 🏗️ Current Architecture

```
User (WhatsApp / Web)
        ↓
FastAPI Webhook / API
        ↓
User Identification (phone / UUID)
        ↓
Message Storage (PostgreSQL)
        ↓
Context Builder
   ├── Chat Memory
   └── Inventory Retrieval (SQL keyword search)
        ↓
Groq LLM
        ↓
Response → User
```

---

## ✅ Current Features

### 1. Webhook Handling

* GET `/webhook` → verification
* POST `/webhook` → receives WhatsApp messages
* Extracts user message from webhook payload

### 2. User Management

* Unified `users` table supports:

  * WhatsApp users (phone number)
  * Web users (UUID)

### 3. Message Persistence

* All conversations stored in PostgreSQL
* Used for:

  * Memory
  * Debugging
  * Analytics (future)

### 4. Basic RAG (Current)

* Retrieval from `inventory_items` table
* Keyword-based SQL search (`ILIKE`)
* Simple ranking by match location
* Context injected into LLM prompt

### 5. Memory

* Fetches recent messages for context
* Improves conversational continuity

---

## ⚠️ Current Limitations

This is **not a full RAG system yet**:

* ❌ No semantic (embedding-based) retrieval
* ❌ No fuzzy matching
* ❌ No structured context (plain text only)
* ❌ No ranking by business logic
* ❌ No retrieval observability/debugging
* ❌ No ingestion pipeline (manual DB inserts)

👉 Current stage: **“Retrieval-Augmented Prompting”**

---

## 🚀 Target Architecture (Upgraded RAG)

```
User Query
   ↓
Query Understanding (intent + entities)
   ↓
Hybrid Retrieval
   ├── SQL (exact match)
   ├── Fuzzy Search (pg_trgm)
   └── Vector Search (embeddings)
   ↓
Business Ranking Layer
   ↓
Structured Context Builder (JSON)
   ↓
LLM (Groq)
   ↓
Response
```

---

## 🔧 Planned Improvements

### 🔹 Phase 1: Retrieval Improvements

#### 1. Add Retrieval Debugging

* Log:

  * query
  * matched inventory IDs
  * ranking scores

```python
logger.info({
  "query": query,
  "results": results
})
```

---

#### 2. Add Fuzzy Search

Enable PostgreSQL extension:

```sql
CREATE EXTENSION pg_trgm;
```

Use similarity ranking:

```sql
SELECT *, similarity(name, :query) AS score
FROM inventory_items
WHERE name % :query
ORDER BY score DESC
LIMIT 5;
```

---

#### 3. Improve Inventory Schema

Add structured fields:

```sql
brand VARCHAR,
price NUMERIC,
in_stock BOOLEAN,
tags TEXT[],
features JSONB
```

---

### 🔹 Phase 2: Structured Context

Convert retrieved data into structured format:

```json
[
  {
    "name": "Product A",
    "price": 999,
    "features": ["fast", "lightweight"]
  }
]
```

Prompt rule:

```
Only answer using the provided products.
Do not invent any data.
```

---

### 🔹 Phase 3: Vector RAG

Add embeddings using:

* sentence-transformers
* FAISS (initial)

Flow:

```
Text → Embedding → Vector DB
Query → Embedding → Similarity search
```

---

### 🔹 Phase 4: Hybrid Retrieval

Combine:

* SQL results
* Fuzzy results
* Vector results

```python
final_results = merge(sql, fuzzy, vector)
```

👉 Hybrid search improves accuracy and recall ([orkes.io][1])

---

### 🔹 Phase 5: Business Ranking

Add scoring logic:

```python
score = (
  relevance * 0.6 +
  in_stock * 0.2 +
  margin * 0.2
)
```

---

### 🔹 Phase 6: User Intelligence

Store user preferences:

```json
{
  "preferred_category": "electronics",
  "budget_range": "1000-2000"
}
```

Use this for personalized retrieval.

---

### 🔹 Phase 7: Ingestion Pipeline

Add:

* CSV upload endpoint
* Admin API

```
POST /admin/upload-inventory
```

Steps:

* parse CSV
* normalize data
* generate embeddings
* store in DB

---

### 🔹 Phase 8: Observability

Log full RAG pipeline:

```json
{
  "query": "...",
  "retrieved_items": [...],
  "response": "...",
  "latency": 120
}
```

---

## 🗄️ Database Design

### users

* external_id (phone or UUID)
* source (whatsapp / web)

### messages

* user_id
* role (user / assistant)
* content

---

## 🧠 Key Concepts

* RAG improves LLM accuracy by injecting external knowledge dynamically ([GitHub][2])
* Production systems require hybrid retrieval, ranking, and observability ([Medium][3])

---

## 🎯 Goal

Transform system from:

> Basic chatbot with SQL search

➡️ Into:

> Hybrid RAG-based AI sales assistant with semantic retrieval, structured context, and business-aware ranking

---

## 🏁 Next Steps (Priority)

1. Add retrieval logging
2. Enable pg_trgm fuzzy search
3. Implement structured context
4. Add embeddings + FAISS
5. Build hybrid retrieval pipeline

---

## 📌 Resume Description

> Built a hybrid Retrieval-Augmented Generation (RAG) system integrating SQL, fuzzy search, and vector retrieval with persistent conversational memory, enabling context-aware and business-driven AI responses across WhatsApp and web chat platforms.

---

## 📬 Future Extensions

* Tool calling (lead creation, booking)
* Multi-tenant SaaS support
* Redis caching layer
* Real-time analytics dashboard

---

## 🧑‍💻 Author

AI Engineer Project – FastAPI + Groq + RAG System

[1]: https://orkes.io/blog/rag-best-practices/?utm_source=chatgpt.com "Best Practices for Production-Scale RAG Systems"
[2]: https://github.com/Danielskry/Awesome-RAG?utm_source=chatgpt.com "Awesome list of Retrieval-Augmented Generation (RAG) ..."
[3]: https://medium.com/%40shubhodaya.hampiholi/building-production-grade-rag-systems-architecture-evaluation-and-advanced-design-patterns-1d9d649aebfa?utm_source=chatgpt.com "Building Production-Grade RAG Systems: Architecture ..."
