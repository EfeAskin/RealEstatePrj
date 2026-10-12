# CypInvEst — AI-Powered Real Estate Platform

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Neon-4169E1?logo=postgresql&logoColor=white)
![pgvector](https://img.shields.io/badge/pgvector-HNSW-336791)
![OpenAI](https://img.shields.io/badge/OpenAI-embeddings%20%2B%20GPT-412991?logo=openai&logoColor=white)

CypInvEst is a full-stack real estate marketplace for **North Cyprus and Turkey**. Buyers and renters search listings, save favourites and message agents. Agents publish and manage properties. Admins approve listings and handle support tickets.

On top of that sits an **AI layer**. You can search in plain English or Turkish, for example *"cheap 2+1 flat with sea view in Girne under 150k USD"*, and get results ranked by meaning. There's also a conversational property assistant and a content-based recommendation engine. If no OpenAI key is configured, the app still runs and search falls back to keyword matching.

---

## Table of contents

- [Features](#features)
- [How the AI search works](#how-the-ai-search-works)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Scripts](#scripts)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Architecture notes](#architecture-notes)
- [Team](#team)

---

## Features

**For users**
- Browse and filter listings by type, price, rooms, location and amenities, with several sort orders
- **AI semantic search** that accepts natural-language queries in English, Turkish or a mix of both
- **AI chat assistant** (`/aichat`) that finds listings conversationally, with saved, ChatGPT-style conversation threads
- "Similar listings" on property pages and personalised recommendations
- Favourites, real-time user↔agent messaging and support tickets

**For agents**
- Publish listings with multiple photos and a cover image, plus date-based rental pricing
- Manage your own properties and incoming customer requests
- A profile that adapts to your role (company and IBAN fields for agents)

**For admins**
- A listing approval workflow (pending → active / inactive)
- User and property management, a dashboard, and system and sales logs
- A support-ticket inbox with per-ticket chat rooms

**Platform**
- Role-based access control (**User / Agent / Admin**) with bcrypt-hashed passwords
- Prices stored in **GBP, TRY, EUR or USD**, compared through live, cached exchange rates
- A responsive "glassmorphism" UI with a mobile web view

---

## How the AI search works

```
"cheap 2+1 flat with sea view in Girne under 150k USD"
        │
 [1] place normalisation      girne → Kyrenia                     (dictionary, no API call)
 [2] constraint extraction    GPT → {type, beds, city, max_price, currency, …}
                              every field re-validated against real DB values
 [3] SQL candidate filter     hard filters + currency-aware price; relaxes if too few results
 [4] hybrid rerank            0.70·cosine(pgvector HNSW) + 0.15·keyword + 0.10·rating + 0.05·recency
 [5] relevance gate + rerank  drops off-topic queries; optional GPT precision rerank
        │
     ranked listings
```

Each property is turned into a descriptive sentence built from its structured fields and its bilingual amenity names. That sentence is embedded with `text-embedding-3-small` (1536 dimensions) and stored in a `vector(1536)` column with an HNSW cosine index. Every AI step **fails soft**: if a step errors, search drops back to the next simpler path instead of failing.

For the full walkthrough, see **[docs/AI_SEARCH.md](docs/AI_SEARCH.md)**.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Uvicorn, Jinja2 server-rendered templates |
| Database | PostgreSQL on [Neon](https://neon.tech) (serverless), `psycopg2` connection pool |
| Vector search | `pgvector` (HNSW index, cosine distance), `pg_trgm`, `unaccent` |
| AI | OpenAI `text-embedding-3-small` (embeddings), `gpt-4o-mini` (query parsing, chat, rerank) |
| Auth | Cookie sessions, bcrypt password hashing, role-based access |
| Frontend | HTML/CSS/vanilla JS, responsive layout |

---

## Project structure

```text
RealEstatePrj/
├── app/                        # The FastAPI application (Python package)
│   ├── main.py                 # App entry point: middleware, static mounts, router registration
│   ├── paths.py                # Absolute paths for templates / static / uploads
│   ├── database.py             # Data-access facade + request-scoped auth helpers
│   ├── db/                     # SQL data-access layer
│   │   ├── connection.py       #   pooled Neon connection (ThreadedConnectionPool)
│   │   ├── auth_user.py        #   users, login, registration
│   │   ├── properties.py       #   listings, images, features, agents
│   │   └── db_admin.py         #   approvals, logs, admin queries
│   ├── routers/                # HTTP routes, one module per feature
│   │   ├── auth.py  pages.py  listings.py  properties.py  property_filter.py
│   │   ├── profile.py  favorites.py  chat.py  messages.py  tickets.py  admin.py
│   │   ├── ai_search.py        #   JSON AI endpoints (search, similar, recommendations)
│   │   └── aichat.py           #   conversational AI assistant + chat history
│   ├── services/               # AI layer
│   │   ├── openai_client.py    #   embeddings, GPT extraction, relevance gate, rerank
│   │   ├── query_pipeline.py   #   the multi-stage semantic search orchestrator
│   │   ├── constraint_extractor.py  document_builder.py  recommendations.py
│   │   └── place_aliases.py  currency.py  ai_config.py
│   ├── templates/              # Jinja2 pages (+ includes/ for shared components)
│   └── static/                 # CSS and images (htmlfotos/ holds uploaded photos)
├── scripts/
│   ├── schema.sql              # Full DB schema; use it to set up a fresh database
│   ├── seed_features.sql       # Amenity checklist reference data
│   ├── migrations/             # Incremental migrations (001–006) for existing databases
│   ├── run_migration.py        # Applies a .sql file to DATABASE_URL
│   ├── backfill_embeddings.py  # Generates/refreshes property embeddings
│   └── validate_pgvector.py    # End-to-end pgvector check (rolled back, writes nothing)
├── tests/
│   └── test_ai_offline.py      # AI logic tests; no DB, network or API key needed
├── docs/                       # AI search deep-dive, design notes
├── .env.example                # Template for your local .env
└── requirements.txt
```

---

## Getting started

### 1. Prerequisites

- **Python 3.10+** (developed on 3.11)
- A **PostgreSQL** database with the `pgvector` extension. A free [Neon](https://neon.tech) project is the easiest option because pgvector is built in.
- *(Optional)* An **OpenAI API key** to enable the AI features

### 2. Clone and install

```bash
git clone https://github.com/EfeAskin/RealEstatePrj.git
cd RealEstatePrj

python -m venv venv
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the template and fill in your values:

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | ✅ | PostgreSQL connection string, e.g. `postgresql://user:pass@host.neon.tech/db?sslmode=require` |
| `OPENAI_API_KEY` | optional | Turns on semantic search, recommendations and the AI chat |

### 4. Create the database schema

On a **new, empty** database, create every table and load the amenity list:

```bash
python scripts/run_migration.py scripts/schema.sql
python scripts/run_migration.py scripts/seed_features.sql
```

> `schema.sql` already includes migrations `001–006`. Run the files in `scripts/migrations/` only when you're upgrading an older database that already has data.

### 5. Run the app

```bash
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**, pick a role, and register.

### 6. Enable the AI features (optional)

Add `OPENAI_API_KEY` to `.env`. Once you have some listings, generate their embeddings:

```bash
python scripts/backfill_embeddings.py          # only new or changed listings
python scripts/backfill_embeddings.py --all    # force a full re-embed
```

Then try a natural-language query on `/search`, chat with the assistant at `/aichat`, or call the JSON API:

```
GET /api/ai-search?q=3 bedroom villa with pool in Kyrenia
GET /api/properties/{id}/similar
GET /api/recommendations              (requires login)
```

### 7. Create an admin account

Admins can't sign up from the UI. Register a normal user first, then promote that account in SQL:

```sql
UPDATE users SET role = 'admin' WHERE email = 'you@example.com';
```

Then sign in at `/login/admin`.

---

## Scripts

Run these from the project root with the virtual environment active.

| Command | What it does |
|---|---|
| `python scripts/run_migration.py <file.sql>` | Applies a SQL file to `DATABASE_URL` and prints the target host first |
| `python scripts/backfill_embeddings.py [--all]` | Embeds listings that are new or changed. Idempotent and resumable. |
| `python scripts/validate_pgvector.py` | Checks pgvector ranking end-to-end without OpenAI; the transaction is rolled back |
| `python tests/test_ai_offline.py` | Runs the offline AI test suite |

---

## Testing

```bash
python tests/test_ai_offline.py
```

This covers place normalisation, embedding-document building, candidate-SQL generation (location robustness), the hybrid ranking SQL, the LLM rerank helpers, the relevance gate and graceful degradation without a key. It needs no database, network or API key, and prints `PASS`/`FAIL` per check followed by `ALL PASS`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Activate the virtual environment and run `pip install -r requirements.txt` |
| `ModuleNotFoundError: No module named 'app'` | Run commands from the project root, not from inside `app/` |
| `Port 8000 is already in use` | Start on another port: `uvicorn app.main:app --reload --port 8001` |
| Database connection errors | Check `DATABASE_URL` in `.env`. Neon URLs must end with `?sslmode=require`. |
| `type "vector" does not exist` | Enable pgvector on your Postgres; Neon has it built in |
| Search only does keyword matching | `OPENAI_API_KEY` is missing or invalid, or the embeddings haven't been backfilled yet |
| `UnicodeEncodeError` on Windows | Set `PYTHONIOENCODING=utf-8` before running scripts that print Turkish text |

---

## Architecture notes

- **Request flow.** `app/main.py` builds the app, mounts `/static`, and registers every router. An HTTP middleware resolves the logged-in user from the `user_id` cookie once per request, using a short-TTL cache, and exposes it to templates. Static requests skip the database entirely.
- **Data layer.** `app/db/connection.py` owns a `ThreadedConnectionPool`. `conn.close()` returns the connection to the pool instead of closing the socket. `app/database.py` re-exports the data-access functions plus the request-scoped auth helpers `get_user_from_request`, `can_user_modify_property` and `is_admin_user`.
- **Flat schema.** A single `properties` table holds free-text geography (`city` / `district` / `country`) and the `embedding vector(1536)` column. Prices are stored in each listing's own currency (`price_normalized` + `currency_code`), so every price comparison converts currencies first.
- **Images.** Uploaded files go to `app/static/htmlfotos/`. The database stores a relative path such as `htmlfotos/<file>`. Imported listings can use absolute `http(s)` URLs instead.
- **Graceful AI degradation.** `ai_config.ai_enabled()` is true only when a key is set and the SDK imports. Every AI call returns `None`/`[]` on failure, and the routes fall back to keyword `ILIKE` search.

---

## Team

Built as a team project by:

- **Kamil Efe Aşkın** ([@EfeAskin](https://github.com/EfeAskin)): platform, UI/UX, authentication, admin panel, messaging, support tickets
- **Begench Tekayev** ([@begench-tek](https://github.com/begench-tek)): AI semantic search and recommendation engine, AI chat assistant and history, database migrations and performance

### Contributing

Day-to-day development happens on the `demoproject` branch, and changes reach `main` through pull requests reviewed by the repository owner. Never commit `.env` or API keys.
