<!-- README.md -->

# 🧠 RAG-Based Text-to-SQL Agent

A production-grade natural language to SQL system powered by **RAG (Retrieval-Augmented Generation)**, **few-shot learning**, **Chain-of-Thought reasoning**, and **multi-layer safety guardrails**. Built with FastAPI and fully containerized with Docker Compose.

---

## ✨ Key Features

- **Natural Language → SQL** — Ask business questions in plain English; get validated, executable SQL.
- **RAG-Powered Context** — Retrieves relevant schema and SQL examples via pgvector semantic search.
- **Few-Shot Learning** — Injects proven query patterns from a knowledge base to improve accuracy.
- **Chain-of-Thought (CoT)** — Exposes step-by-step reasoning (`query_plan`) for full transparency.
- **Multi-Layer Validation** — SQL syntax check (sqlglot) → Semantic guard (LLM) → EXPLAIN gate (MySQL).
- **Self-Healing** — Automatically attempts to repair failed SQL via an LLM-based repair loop.
- **Smart Caching** — Redis-backed caching with schema/examples versioning for instant repeat queries.
- **Auto Schema Profiling** — Automatically introspects MySQL schema and generates a data dictionary.
- **Fully Dockerized** — One-command setup with Docker Compose.

---

## 🏗️ Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                        FastAPI Server                        │
│                                                              │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │  /query   │──▶│ Redis Cache  │──▶│  Return cached result│ │
│  │  /run     │   │  (hit?)      │   └──────────────────────┘ │
│  │  /debug   │   └──────┬───────┘                            │
│  └──────────┘          │ miss                                │
│                        ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              Build Generation Context                    │ │
│  │  ┌─────────────────┐   ┌──────────────────────────────┐ │ │
│  │  │ Schema RAG       │   │ Few-Shot Example Retrieval   │ │ │
│  │  │ (pgvector)       │   │ (pgvector)                   │ │ │
│  │  └─────────────────┘   └──────────────────────────────┘ │ │
│  └──────────────────────────┬──────────────────────────────┘ │
│                             ▼                                │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │           LLM SQL Generation (Ollama)                    │ │
│  │           with CoT query_plan                            │ │
│  └──────────────────────────┬──────────────────────────────┘ │
│                             ▼                                │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              Multi-Layer Validation                      │ │
│  │  1. sqlglot syntax check                                 │ │
│  │  2. Semantic guard (LLM-based)                           │ │
│  │  3. EXPLAIN gate (MySQL execution plan)                  │ │
│  └──────────────────────────┬──────────────────────────────┘ │
│                             ▼                                │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐   │
│  │ Execute SQL  │   │ Cache Result │   │ Return Response│   │
│  │ (MySQL)      │──▶│ (Redis)      │──▶│ to Client      │   │
│  └──────────────┘   └──────────────┘   └────────────────┘   │
│                                                              │
│         On failure: LLM Repair Loop → Re-validate            │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Component       | Technology                       |
| --------------- | -------------------------------- |
| API Framework   | FastAPI + Uvicorn                |
| LLM             | Ollama (llama3)                  |
| Embedding       | nomic-embed-text (via Ollama)    |
| Vector Store    | PostgreSQL + pgvector            |
| Business DB     | MySQL 8.0                        |
| Cache           | Redis 7                          |
| SQL Validation  | sqlglot                          |
| Containerization| Docker Compose                   |

---

## 📁 Project Structure

```
.
├── app/
│   ├── main.py                  # FastAPI entry point
│   ├── config.py                # Centralized configuration (env vars)
│   ├── api/
│   │   └── routes.py            # API endpoint definitions
│   ├── models/
│   │   └── schemas.py           # Pydantic request/response models
│   ├── services/
│   │   ├── llm_service.py       # LLM interaction, prompt building, SQL generation & repair
│   │   ├── embedding_service.py # Text → vector embedding via Ollama
│   │   ├── guard_service.py     # SQL validation (sqlglot) + semantic guard (LLM)
│   │   ├── schema_service.py    # MySQL schema introspection & sync to pgvector
│   │   ├── mysql_service.py     # MySQL query execution & EXPLAIN gate
│   │   ├── postgres_service.py  # pgvector operations (schema + examples storage)
│   │   └── redis_service.py     # Caching, versioning, and cache invalidation
│   └── scripts/
│       └── auto_profiler.py     # Auto-profile MySQL tables → data dictionary
├── docker/
│   ├── api.Dockerfile           # API service container
│   ├── mysql-init/              # MySQL initialization scripts
│   └── postgres-init/           # PostgreSQL/pgvector initialization scripts
├── docker-compose.yml           # Full stack orchestration
├── dictionary.yaml              # Data dictionary (column descriptions & value profiles)
├── requirements.txt             # Python dependencies
├── tests/                       # Test suite
└── LICENSE                      # MIT License
```

---

## 🚀 Quick Start

### Prerequisites

- [Docker](https://www.docker.com/) and Docker Compose installed
- Sufficient memory for Ollama models (~4 GB+ recommended)

### 1. Clone the Repository

```bash
git clone https://github.com/Kyle7994/RAG-Based-TextToSQL-Agent.git
cd RAG-Based-TextToSQL-Agent
```

### 2. Start All Services

```bash
docker compose up -d
```

This brings up **MySQL**, **PostgreSQL (pgvector)**, **Redis**, **Ollama**, and the **FastAPI API server**.

### 3. Pull Required Models (first time only)

```bash
docker compose exec ollama ollama pull llama3
docker compose exec ollama ollama pull nomic-embed-text
```

### 4. Sync Schema

Initialize the RAG schema context by introspecting the MySQL database:

```bash
curl -X POST http://localhost:8000/system/sync-schema
```

### 5. (Optional) Run Auto Profiler

Generate a data dictionary with column-level descriptions:

```bash
docker compose exec api python -m app.scripts.auto_profiler
```

---

## 📡 API Reference

### Health Check

```
GET /health
```

Returns `{"status": "ok"}` when the service is running.

### Run a Query

```
POST /query/run
Content-Type: application/json

{
  "question": "What is the total revenue from non-VIP users who bought Accessories, grouped by country?"
}
```

**Response:**
```json
{
  "question": "...",
  "query_plan": "Step 1: Join users → orders → order_items → products. Step 2: Filter non-VIP + paid + Accessories. Step 3: Aggregate revenue by country.",
  "sql": "SELECT u.country, SUM(p.price * oi.quantity) AS total_revenue FROM users u JOIN orders o ON u.id = o.user_id JOIN order_items oi ON o.id = oi.order_id JOIN products p ON oi.product_id = p.id WHERE u.is_vip = FALSE AND o.status = 'paid' AND p.category = 'Accessories' GROUP BY u.country ORDER BY total_revenue DESC",
  "columns": ["country", "total_revenue"],
  "rows": [["DE", 1250.00], ["CA", 980.50]],
  "error": null,
  "cache_status": "success",
  "is_cached": false
}
```

### Debug a Query (no execution)

```
POST /query/debug
Content-Type: application/json

{
  "question": "How many orders were cancelled last month?"
}
```

Returns the generated SQL, query plan, validation results, and full debug info **without executing** the query.

### Sync Schema

```
POST /system/sync-schema
```

Introspects the MySQL database and syncs schema metadata + embeddings to pgvector.

### Add a Few-Shot Example

```
POST /system/add-example
Content-Type: application/json

{
  "question": "Get total revenue per country for VIP users",
  "sql": "SELECT u.country, SUM(p.price * oi.quantity) AS total_revenue FROM users u JOIN orders o ON u.id = o.user_id JOIN order_items oi ON o.id = oi.order_id JOIN products p ON oi.product_id = p.id WHERE u.is_vip = TRUE AND o.status = 'paid' GROUP BY u.country ORDER BY total_revenue DESC"
}
```

Adds a verified question-SQL pair to the knowledge base for future few-shot retrieval.

---

## ⚙️ Configuration

All settings are configured via **environment variables** (see `docker-compose.yml`):

| Variable           | Default              | Description                                 |
| ------------------ | -------------------- | ------------------------------------------- |
| `MYSQL_HOST`       | `mysql`              | MySQL hostname                              |
| `MYSQL_PORT`       | `3306`               | MySQL port                                  |
| `MYSQL_DB`         | `ecommerce`          | MySQL database name                         |
| `PG_HOST`          | `postgres`           | PostgreSQL hostname                         |
| `PG_DB`            | `retrieval`          | PostgreSQL database for vector storage      |
| `REDIS_HOST`       | `redis`              | Redis hostname                              |
| `LLM_BASE_URL`     | `http://ollama:11434`| Ollama API base URL                         |
| `LLM_MODEL`        | `llama3`             | LLM model name                              |
| `EMBED_MODEL`      | `nomic-embed-text`   | Embedding model name                        |
| `PROMPT_VERSION`   | `prompt_v4`          | Active prompt template version              |
| `GUARD_VERSION`    | `guard_v3`           | Active semantic guard version               |
| `VALIDATOR_VERSION`| `validator_v2`       | Active SQL validator version                |
| `ENABLE_ADMIN_OPS` | `false`              | Enable destructive SQL operations           |

---

## 🔒 Safety & Guardrails

This system implements a **defense-in-depth** approach to SQL safety:

1. **SQL Syntax Validation** — Uses `sqlglot` to parse and validate SQL before execution.
2. **Semantic Guard** — An LLM-based check that verifies the generated SQL matches the user's intent and the schema context.
3. **EXPLAIN Gate** — Runs `EXPLAIN` on the generated SQL against MySQL to detect full table scans or problematic execution plans.
4. **Admin Ops Guard** — Blocks `DELETE`, `UPDATE`, `DROP`, and other destructive operations unless explicitly enabled.
5. **Self-Correction** — On failure, the system automatically attempts a repair cycle through the LLM.

---

## 🧪 Testing

Shell-based integration tests are included:

```bash
# Run the NL2SQL test suite
bash test_nl2sql.sh

# Run the extended test suite
bash test2.sh
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).