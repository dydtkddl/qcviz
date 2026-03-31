# MolChat v3 Deep Scan Integrated Report

Generated from the completed Phase 0~10 project scan.

Project: `MolChat v3`
Report Date: `2026-03-28 17:16:23 +09:00`
Workspace Root: `C:\Users\user\Desktop\molcaht\molchat\v3`
Scanned File Count: `178`
Scanned Line Count: `60,146`
Important Note: This report is fact-based on the scanned repository state. Where the codebase is inconsistent, the implementation is treated as source of truth and the drift is documented explicitly.

## Table of Contents

1. [DOCUMENT 1 — ARCHITECTURE.md](#-document-1--architecturemd)
2. [DOCUMENT 2 — DATA_MODEL.md](#-document-2--data_modelmd)
3. [DOCUMENT 3 — API_REFERENCE.md](#-document-3--api_referencemd)
4. [DOCUMENT 4 — DEVELOPMENT_SETUP.md](#-document-4--development_setupmd)
5. [DOCUMENT 5 — PROJECT_CONTEXT.md](#-document-5--project_contextmd)
6. [Scan Metadata](#scan-metadata)

---

# 📄 DOCUMENT 1 — ARCHITECTURE.md

## 1. Executive Summary

### 1.1 Project One-Line Definition

MolChat v3 is a chemistry-focused conversational application that combines a FastAPI backend, a Next.js frontend, LLM-driven reasoning, molecule search, structure generation, and cached molecule intelligence views.

### 1.2 Core Business Goals

- Allow a user to ask chemistry and molecule-related questions in natural language.
- Resolve molecules from names, identifiers, or structural text.
- Search across local and external chemistry providers.
- Generate or retrieve 2D/3D structural data.
- Present a richer molecule card including properties, safety, similarity, and AI summary.
- Support iterative conversation by persisting chat sessions and message history.

### 1.3 Technical Mission Statement

The technical mission of this repository is to provide a modular full-stack system where:

- the frontend offers a conversational and molecule-centric UI,
- the backend orchestrates conversation, tool use, persistence, and molecule enrichment,
- Redis accelerates cache, rate limit, and queue workflows,
- PostgreSQL stores durable domain data,
- Gemini and Ollama provide LLM capability with fallback routing,
- chemistry-specific services enrich and calculate molecular information.

### 1.4 Current State Assessment

The codebase is architecturally recognizable and reasonably modular, but it is not fully aligned with its own documentation:

- the implementation is a modular monolith, not a fully clean-layered system,
- deployment docs and Docker assets drift from the current tree,
- a dormant knowledge/RAG subsystem is present in code but not in schema,
- the frontend contains overlapping architectures from an unfinished refactor,
- several production-significant defects exist in active paths.

## 2. System Context (C4 Level 1)

### 2.1 Context Diagram

```text
┌──────────────────────┐
│ End User             │
│ Web browser user     │
└──────────┬───────────┘
           │ HTTPS / WebSocket
           v
┌──────────────────────────────────────────────┐
│ MolChat v3                                   │
│ Full-stack molecule intelligence application │
└───────┬───────────────┬───────────────┬──────┘
        │               │               │
        │ REST/SQL      │ TCP / Redis   │ HTTPS
        v               v               v
┌──────────────┐  ┌──────────────┐  ┌────────────────────┐
│ PostgreSQL   │  │ Redis        │  │ External Chemistry │
│ sessions     │  │ cache/queue  │  │ APIs               │
│ molecules    │  │ rate limit   │  │ PubChem, ChEMBL,   │
│ feedback     │  │ worker state │  │ ChemSpider, ZINC   │
└──────────────┘  └──────────────┘  └────────────────────┘
        │
        │ internal service calls
        v
┌────────────────────┐
│ LLM Providers      │
│ Gemini / Ollama    │
└────────────────────┘
```

### 2.2 External Actors

| Actor | Role | Communication | Notes |
|---|---|---|---|
| End user | asks questions, views molecules, downloads structures | browser HTTP(S), SSE-like stream, WebSocket | active primary actor |
| PostgreSQL | durable storage | SQLAlchemy async over TCP | stores sessions, chat, molecules, feedback |
| Redis | cache, rate limit, queue state | redis async client | used for hot cache, request limits, queue |
| Gemini | primary cloud LLM | HTTPS via `google-genai` | selected first when configured and healthy |
| Ollama | fallback local LLM | HTTP to Ollama API | used as model fallback |
| PubChem | primary chemistry source | HTTP PUG-REST | used for search, CID resolution, properties, SDF |
| ChEMBL | enrichment source | HTTP | used in search aggregation |
| ChemSpider | optional enrichment source | HTTP | API key supported but optional |
| ZINC | search source | HTTP | used in layer0 federation |
| Nginx / reverse proxy | intended public entrypoint | HTTPS reverse proxy | implied by docs and basePath strategy |

### 2.3 External Communication Summary

- Browser to frontend: standard Next.js page navigation.
- Browser to backend: proxied REST from frontend, plus `/ws/chat/{session_id}` WebSocket.
- Backend to Postgres: async SQLAlchemy / asyncpg.
- Backend to Redis: async Redis client.
- Backend to LLM providers: HTTP-based API clients.
- Backend to chemistry providers: HTTP queries from provider services and direct router patches.

## 3. Container Diagram (C4 Level 2)

### 3.1 Intended Container Topology

```text
┌────────────────────────────────────────────────────────────────────┐
│ User Browser                                                       │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               │ HTTPS / WebSocket
                               v
┌────────────────────────────────────────────────────────────────────┐
│ Frontend Container                                                 │
│ Next.js 14 app on port 3000                                        │
│ Path base: /molchat                                                │
└──────────────────────────────┬─────────────────────────────────────┘
                               │
                               │ HTTP proxy / fetch
                               v
┌────────────────────────────────────────────────────────────────────┐
│ API Container                                                      │
│ FastAPI app                                                        │
│ Routes: /api/v1/* and /ws/chat/{session_id}                        │
└──────┬──────────────────┬────────────────────┬─────────────────────┘
       │                  │                    │
       │ SQL              │ Redis             │ HTTP
       v                  v                    v
┌──────────────┐   ┌──────────────┐   ┌──────────────────────────────┐
│ PostgreSQL   │   │ Redis        │   │ External Services             │
│ 5432/5433    │   │ 6379         │   │ Gemini, Ollama, PubChem,     │
│ domain store │   │ cache/queue  │   │ ChEMBL, ChemSpider, ZINC     │
└──────────────┘   └──────────────┘   └──────────────────────────────┘
       ^
       │ Redis queue + DB read/write
       │
┌──────┴─────────────────────────────────────────────────────────────┐
│ xTB Worker Container                                               │
│ background calculation worker                                      │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 Actual Repository Containers vs Runtime Paths

| Container | Declared In | Actual Status |
|---|---|---|
| `frontend` | `docker-compose.yml` | declared, but `frontend/Dockerfile` missing |
| `api` | `docker-compose.yml` | declared, but `backend/Dockerfile` missing |
| `xtb-worker` | `docker-compose.yml` | declared, but `backend/Dockerfile.xtb` missing |
| `postgres` | `docker-compose.yml` | declared and coherent |
| `redis` | `docker-compose.yml` | declared and coherent |
| `ollama` | `docker-compose.yml` | declared and coherent |

### 3.3 Protocols Between Containers

| Source | Target | Protocol | Purpose |
|---|---|---|---|
| Browser | Frontend | HTTPS | page and asset delivery |
| Browser | Backend | WebSocket | streaming chat events |
| Frontend | Backend | HTTP/JSON | REST API access |
| Backend | PostgreSQL | SQL / TCP | persistence |
| Backend | Redis | Redis protocol | cache, rate limit, queue |
| Backend | Ollama | HTTP | fallback LLM |
| Backend | Gemini | HTTPS | primary LLM |
| Backend | PubChem | HTTPS | molecule resolution and data |
| Backend | ChEMBL/ChemSpider/ZINC | HTTPS | federated search |
| Worker | Redis | Redis protocol | task pull/status |
| Worker | PostgreSQL | SQL / TCP | result lookup/persistence |

### 3.4 Port Map

| Service | Compose Port | WSL Script Port | Notes |
|---|---:|---:|---|
| frontend | 3000 | 3000 | consistent |
| api | 8000 | 8333 | inconsistent between compose and scripts |
| postgres | 5433 -> 5432 | 5433 | consistent for local host access |
| redis | 6379 | 6379 | consistent |
| ollama | 11434 | 11434 | consistent |

## 4. Component Diagram (C4 Level 3)

### 4.1 Backend Components

```text
main.py
  -> middleware package
  -> routers package

routers/chat.py
  -> MolChatAgent
  -> session/message persistence helpers

routers/molecules.py
  -> MoleculeOrchestrator
  -> RDKit / format conversion helpers
  -> CalculationQueue

MolChatAgent
  -> PromptBuilder
  -> FallbackRouter
  -> ToolRegistry
  -> HallucinationGuard

MoleculeOrchestrator
  -> QueryResolver
  -> SearchAggregator
  -> Layer0 providers
  -> Layer1 structure services
  -> Layer2 calculation services
  -> cache manager
```

### 4.2 Frontend Components

```text
app/layout.tsx
  -> global shell
  -> Header
  -> RouteProgress

app/chat/page.tsx
  -> direct local state chat flow
  -> api client
  -> MoleculeCardFull
  -> MoleculePanel

app/molecule/[id]/page.tsx
  -> api client
  -> Viewer3D
  -> PropertyTable

legacy shared chat stack
  -> useChat
  -> websocket.ts
  -> chatStore.ts
  -> ChatWindow / InputBar / MessageBubble
```

### 4.3 Dependency Direction

```text
Frontend route components
  -> frontend lib/api.ts
  -> backend routers
  -> backend services
  -> backend models / schemas
  -> Postgres / Redis / external APIs

backend/routers/*
  -> backend/services/*
  -> backend/core/*
  -> backend/models/*
  -> backend/schemas/*

backend/services/intelligence/*
  -> external LLMs
  -> molecule tools
  -> selected backend services

backend/services/molecule_engine/*
  -> providers
  -> cache manager
  -> DB models
  -> Redis queue
  -> RDKit/xTB subprocess path
```

### 4.4 Boundary Notes

- Routers own HTTP concerns and compose services manually.
- Schemas define transport contracts, not deep domain rules.
- Models are used as both persistence and domain record types.
- Services encapsulate most actual business logic.
- The frontend does not fully separate smart/container vs presentational components in the active `/chat` page.

## 5. Layer Architecture

### 5.1 Layer Model

The repository partially matches a Presentation -> Application -> Domain -> Infrastructure layering pattern.

### 5.2 Presentation Layer

Responsibilities:

- route handling and request parsing,
- response formatting,
- page rendering,
- browser interaction and local state.

Actual files:

| Area | Files |
|---|---|
| Backend presentation | `backend/app/routers/*.py` |
| Frontend presentation | `frontend/src/app/**/*`, `frontend/src/components/**/*` |

### 5.3 Application Layer

Responsibilities:

- use-case orchestration,
- conversation flow,
- search orchestration,
- structure generation pipelines,
- calculation submission,
- card-building workflow.

Actual files:

| Area | Files |
|---|---|
| AI application orchestration | `backend/app/services/intelligence/agent.py`, `fallback_router.py`, `prompt_builder.py` |
| Molecule application orchestration | `backend/app/services/molecule_engine/orchestrator.py`, `query_resolver.py` |
| Queue orchestration | `backend/app/services/molecule_engine/layer2_calculation/task_queue.py`, `backend/app/worker.py` |

### 5.4 Domain Layer

Responsibilities:

- core entities,
- chemistry-specific rule evaluation,
- molecule/provider abstractions,
- response shape semantics.

Actual files:

| Area | Files |
|---|---|
| ORM entity definitions | `backend/app/models/*.py` |
| transport/domain schemas | `backend/app/schemas/*.py` |
| chemistry rules | `backend/app/services/molecule_engine/drug_likeness.py`, `ghs_parser.py` |
| provider abstractions | `backend/app/services/molecule_engine/layer0_search/base.py` |

### 5.5 Infrastructure Layer

Responsibilities:

- database engine,
- Redis client,
- logging,
- auth middleware,
- external HTTP integrations,
- subprocess tool invocation.

Actual files:

| Area | Files |
|---|---|
| config/database/redis | `backend/app/core/config.py`, `database.py`, `redis.py` |
| logging/security | `backend/app/core/logging.py`, `security.py` |
| middleware | `backend/app/middleware/*.py` |
| external integrations | provider modules, LLM clients, xTB runner |

### 5.6 Layer Flow

```text
User action
  -> Next.js page/component
  -> frontend api client
  -> FastAPI router
  -> orchestrator/agent service
  -> cache lookup
  -> DB and/or external providers
  -> domain object / schema build
  -> HTTP response
  -> frontend render
```

### 5.7 Places Where Layering Breaks

- `routers/molecules.py` performs direct chemistry generation logic instead of delegating all work to services.
- `frontend/src/app/chat/page.tsx` contains parsing, fetch orchestration, and display logic in one file.
- `backend/app/models/molecule_card.py` imports `app.core.database.Base`, unlike the rest of the model package which uses `app.models.molecule.Base`.
- WebSocket route builds and manages in-memory conversation history without reusing the same persistence path as REST chat.

## 6. Design Patterns & Principles

### 6.1 Patterns Observed in the Repository

| Pattern | Where Used | Evidence |
|---|---|---|
| Modular monolith | whole backend | domain folders under `services`, single app process |
| Orchestrator | `backend/app/services/molecule_engine/orchestrator.py` | central workflow coordination |
| Fallback router | `backend/app/services/intelligence/fallback_router.py` | Gemini -> Ollama failover |
| Tool registry | `backend/app/services/intelligence/tools/__init__.py` | callable tool dispatch from agent |
| Provider aggregation | `layer0_search/aggregator.py` | federates PubChem/ChEMBL/ChemSpider/ZINC/local |
| Adapter/wrapper | `gemini_client.py`, `ollama_client.py` | normalize provider outputs |
| Middleware pipeline | `backend/app/middleware/*` | auth/rate/error/request-id chain |
| Cache-aside | `cache_manager.py`, `orchestrator.py:get_card` | read cache, fallback to source, write cache |
| Background worker | `backend/app/worker.py` | pulls queued calculations |
| App Router routing | `frontend/src/app/*` | route-by-folder frontend structure |

### 6.2 SOLID Status

| Principle | Status | Notes |
|---|---|---|
| Single Responsibility | mixed | many service files are coherent, but `chat/page.tsx` and `orchestrator.py` are overloaded |
| Open/Closed | partial | provider pattern helps extension, but some router logic is hardcoded |
| Liskov Substitution | partial | provider base classes support it, but not consistently enforced across all integrations |
| Interface Segregation | partial | schemas are relatively focused, but frontend components often take broad prop payloads |
| Dependency Inversion | weak | most wiring is manual and concrete classes are instantiated directly |

### 6.3 DRY / KISS / YAGNI Status

| Principle | Status | Notes |
|---|---|---|
| DRY | violated in places | duplicate session CRUD in two routers, duplicate chat architectures on frontend |
| KISS | violated in hotspots | complex ad hoc molecule parsing and card-fetch logic in active frontend page |
| YAGNI | violated | dormant knowledge stack and compose setup exceed current working surface |

### 6.4 Real Code Example: Manual Wiring

```python
async def _get_orchestrator(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> MoleculeOrchestrator:
    cache = MoleculeCacheManager(redis)
    aggregator = SearchAggregator()
    aggregator.set_local_provider(LocalDBProvider(db))
    return MoleculeOrchestrator(db=db, cache=cache, search_aggregator=aggregator)
```

Source: `backend/app/routers/molecules.py`

Interpretation:

- no DI container is present,
- dependencies are assembled directly in the route layer,
- testing and lifecycle management depend on explicit manual composition.

## 7. Cross-Cutting Concerns

### 7.1 Authentication and Authorization

Implementation files:

- `backend/app/middleware/auth.py`
- `backend/app/core/security.py`
- `backend/app/models/audit.py`

Behavior:

- supports `X-API-Key` and JWT bearer validation,
- public endpoints include health, docs, metrics, and `/api/v1/molecules/search`,
- development mode allows requests through without credentials,
- there is no role-based authorization layer,
- there are no user signup/login/refresh endpoints in the repo.

### 7.2 Logging

Implementation files:

- `backend/app/core/logging.py`
- `backend/app/middleware/request_id.py`
- `structlog` usage across routers/services

Behavior:

- request IDs are attached through middleware,
- backend logs are structured,
- frontend still uses direct `console.log` statements in active paths.

### 7.3 Error Handling

Implementation files:

- `backend/app/middleware/error_handler.py`
- route-level `HTTPException` raises

Behavior:

- unified JSON error envelope through middleware,
- custom `MolChatError` hierarchy exists,
- some routes still raise raw `HTTPException`,
- duplicate `RateLimitError` definition exists inside the error handler module.

### 7.4 Caching

Implementation files:

- `backend/app/core/redis.py`
- `backend/app/services/molecule_engine/cache_manager.py`
- `backend/app/services/molecule_engine/orchestrator.py`

Behavior:

- search/detail/card caches use Redis,
- card cache also tries DB persistence via `molecule_card_cache`,
- cache-aside strategy is used,
- DB cache model exists but migration is missing.

### 7.5 Rate Limiting

Implementation files:

- `backend/app/middleware/rate_limiter.py`

Behavior:

- Redis sorted-set sliding window,
- configured by `RATE_LIMIT_REQUESTS` and `RATE_LIMIT_WINDOW`,
- fail-open if Redis errors.

### 7.6 Configuration

Implementation files:

- `backend/app/core/config.py`
- `frontend/src/lib/runtime-config.ts`
- `frontend/next.config.mjs`
- shell scripts in root

Behavior:

- backend settings come from env via Pydantic,
- frontend uses `next.config.mjs` env + rewrites,
- runtime pathing diverges between compose and WSL scripts.

### 7.7 Observability

Implementation files:

- `backend/app/routers/health.py`
- Prometheus deps declared in `backend/pyproject.toml`

Behavior:

- health endpoints exist,
- Prometheus libraries are declared,
- no explicit metrics router file was found in this repo state.

### 7.8 Internationalization

Implementation status:

- no formal i18n framework is present,
- UI strings and comments mix English and Korean,
- prompt templates and UX copy include Korean language content.

## 8. Architecture Decision Records (ADR) Summary

### ADR-01: Use a Modular Monolith Instead of Split Services

- Background:
  MolChat combines chat, molecule search, structure generation, and calculation status.
- Alternatives Considered:
  split chat, search, and calculation into separate services;
  serverless per endpoint;
  keep one backend process.
- Decision:
  keep a single FastAPI application with service modules and one worker.
- Evidence:
  `backend/app/main.py`, `backend/app/services/*`, `backend/app/worker.py`
- Consequences:
  easier local development and direct data access;
  tighter coupling in orchestrators;
  fewer network boundaries, but more shared failure surface.

### ADR-02: Use Gemini First, Ollama as Fallback

- Background:
  the system needs usable LLM quality with a local fallback path.
- Alternatives Considered:
  cloud only;
  local only;
  cost-based selector;
  primary/fallback strategy.
- Decision:
  `FallbackRouter` prefers Gemini when configured and healthy, then falls back to Ollama.
- Evidence:
  `backend/app/services/intelligence/fallback_router.py`
- Consequences:
  balanced quality and resilience;
  adds cost tracking and circuit-breaker complexity;
  increases configuration surface.

### ADR-03: Model Molecule Retrieval as a Three-Layer Engine

- Background:
  the project must search, structure, and calculate molecules through different tools.
- Alternatives Considered:
  a flat utility module;
  a provider-only abstraction;
  layered molecule engine.
- Decision:
  split into layer0 search, layer1 structure, layer2 calculation.
- Evidence:
  `backend/app/services/molecule_engine/layer0_search`
  `backend/app/services/molecule_engine/layer1_structure`
  `backend/app/services/molecule_engine/layer2_calculation`
- Consequences:
  clearer responsibility boundaries;
  easier future extensions;
  orchestration complexity centralizes in `orchestrator.py`.

### ADR-04: Use Redis for Multiple Cross-Cutting Roles

- Background:
  the app needs caching, rate limiting, and queued work without many separate dependencies.
- Alternatives Considered:
  no cache;
  separate cache and queue brokers;
  Redis multipurpose use.
- Decision:
  use Redis as cache, rate-limit store, and queue status broker.
- Evidence:
  `cache_manager.py`, `rate_limiter.py`, `task_queue.py`
- Consequences:
  operational simplicity;
  broader blast radius if Redis fails;
  several code paths fail open.

### ADR-05: Serve the Frontend Under `/molchat`

- Background:
  docs and scripts target subpath deployment behind an existing host.
- Alternatives Considered:
  root deployment;
  separate subdomain;
  basePath deployment.
- Decision:
  set `basePath: '/molchat'` in `frontend/next.config.mjs`.
- Evidence:
  `frontend/next.config.mjs`, `deploy.sh`, `start-frontend.sh`
- Consequences:
  works with reverse proxy subpath;
  increases path-prefix sensitivity;
  several route/link bugs were introduced around this choice.

### ADR-06: Persist Sessions and Messages as First-Class Records

- Background:
  chat history is needed for continuity and UI session lists.
- Alternatives Considered:
  stateless chat only;
  browser-only history;
  persisted server-side sessions.
- Decision:
  store `sessions` and `chat_messages` in PostgreSQL.
- Evidence:
  `backend/app/models/session.py`, `routers/chat.py`, `routers/sessions.py`
- Consequences:
  durable history and analytics;
  duplicate session API surface emerged during evolution;
  title/message_count synchronization must be kept consistent.

## 9. Architecture Risks and Drift Summary

| Area | Issue | Architectural Impact |
|---|---|---|
| Deployment | Dockerfiles referenced by compose are missing | declared topology is not reproducible from repo alone |
| Auth | frontend sends no auth headers; backend dev mode fails open | local behavior masks production auth gaps |
| Frontend | two overlapping chat architectures exist | maintenance cost and regressions increase |
| Data | `knowledge_chunks` and `molecule_card_cache` schema drift | dead or broken subsystems can silently fail |
| Runtime dependencies | RDKit, xTB, `rapidfuzz` are used but not declared in `pyproject.toml` | environment setup is brittle |

## 10. Architecture File Mapping Index

| Concern | Primary Files |
|---|---|
| App bootstrap | `backend/app/main.py` |
| Middleware registration | `backend/app/middleware/__init__.py` |
| Auth | `backend/app/middleware/auth.py`, `backend/app/core/security.py` |
| Health | `backend/app/routers/health.py` |
| Chat | `backend/app/routers/chat.py`, `backend/app/services/intelligence/agent.py` |
| Molecule search/detail | `backend/app/routers/molecules.py`, `backend/app/services/molecule_engine/orchestrator.py` |
| Session persistence | `backend/app/models/session.py`, `backend/app/routers/sessions.py` |
| Feedback | `backend/app/models/feedback.py`, `backend/app/routers/feedback.py` |
| Frontend shell | `frontend/src/app/layout.tsx` |
| Active chat UI | `frontend/src/app/chat/page.tsx` |
| Molecule detail UI | `frontend/src/app/molecule/[id]/page.tsx` |
| Frontend API integration | `frontend/src/lib/api.ts` |
| WebSocket client | `frontend/src/lib/websocket.ts` |

---
# 📄 DOCUMENT 2 — DATA_MODEL.md

## 1. Database Overview

### 1.1 Engine Summary

- Database: PostgreSQL
- Access library: SQLAlchemy 2 async
- Driver: `asyncpg`
- Migration tool: Alembic
- Config source: `backend/app/core/config.py`
- Initial migration file: `backend/alembic/versions/20260220_1504_84284f870ead_initial_schema.py`

### 1.2 Connection Topology

| Aspect | Value |
|---|---|
| Topology | single primary database |
| Read replicas | none found |
| Cluster awareness | none found |
| Sync URL helper | present for Alembic offline mode |
| Pool size | `DB_POOL_SIZE=20` default |
| Max overflow | `DB_MAX_OVERFLOW=10` default |
| Pool timeout | `DB_POOL_TIMEOUT=30` default |

### 1.3 Runtime Connection Assembly

If `DATABASE_URL` is not provided, the backend assembles:

```text
postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}
```

### 1.4 Scope of This Model

This document covers:

- all migrated tables,
- all migrated indexes,
- all ORM-defined but unmigrated cache tables,
- schema drift identified during the scan.

## 2. Complete Entity-Relationship Diagram

### 2.1 Migrated ERD

```text
api_keys
  id PK

audit_logs
  id PK

sessions
  id PK
  └──< chat_messages.session_id
  └──< feedbacks.session_id

chat_messages
  id PK
  session_id FK -> sessions.id
  └──< feedbacks.message_id

molecules
  id PK
  └──< molecule_structures.molecule_id
  └──< molecule_properties.molecule_id

molecule_structures
  id PK
  molecule_id FK -> molecules.id

molecule_properties
  id PK
  molecule_id FK -> molecules.id

feedbacks
  id PK
  message_id FK -> chat_messages.id
  session_id FK -> sessions.id
```

### 2.2 Unmigrated Model Drift

```text
molecule_card_cache
  defined in ORM only
  no Alembic migration found
  used by MoleculeOrchestrator.get_card()
```

### 2.3 Missing Table Drift

```text
knowledge_chunks
  referenced by knowledge services
  no ORM model in migrated set
  no Alembic migration found
```

## 3. Entity Catalog

### 3.1 `api_keys`

Business meaning:

- stores hashed API keys for non-user client authentication.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, not null | API key record ID |
| `key_hash` | string(64) | unique, indexed, not null | hashed key |
| `name` | string(256) | not null | display name |
| `is_active` | boolean | not null | activation flag |
| `rate_limit` | integer | not null | per-key rate limit |
| `last_used_at` | timestamptz | nullable | last usage timestamp |
| `created_at` | timestamptz | default now, not null | creation time |
| `updated_at` | timestamptz | default now, not null | last update |

### 3.2 `audit_logs`

Business meaning:

- immutable log of sensitive actions such as API key usage and security-relevant operations.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, not null | audit row ID |
| `action` | string(100) | not null | event name |
| `actor` | string(256) | nullable | user, api key, or system actor |
| `resource_type` | string(50) | nullable | resource class |
| `resource_id` | string(256) | nullable | resource identifier |
| `details` | JSONB | nullable | structured payload |
| `ip_address` | string(45) | nullable | client IP |
| `user_agent` | text | nullable | request UA |
| `created_at` | timestamptz | default now, not null | event time |

### 3.3 `molecules`

Business meaning:

- canonical durable record for each unique compound known to the system.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, not null | internal molecule ID |
| `cid` | integer | unique, indexed, nullable | PubChem CID |
| `name` | string(512) | indexed, not null | primary display name |
| `canonical_smiles` | text | not null | canonical SMILES |
| `inchi` | text | nullable | InChI identifier |
| `inchikey` | string(27) | unique, indexed, nullable | InChIKey |
| `molecular_formula` | string(256) | nullable | chemical formula |
| `molecular_weight` | float | nullable | molecular weight |
| `properties` | JSONB | nullable | source and scoring metadata |
| `search_vector` | TSVECTOR | nullable | full-text search field |
| `is_deleted` | boolean | not null | soft delete flag |
| `created_at` | timestamptz | default now, not null | creation time |
| `updated_at` | timestamptz | default now, not null | last update |

### 3.4 `sessions`

Business meaning:

- top-level chat thread metadata.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, not null | session ID |
| `title` | string(512) | nullable | session title |
| `user_identifier` | string(256) | indexed, nullable | external user marker |
| `model_used` | string(100) | nullable | preferred/used model |
| `message_count` | integer | not null | stored message count |
| `metadata_extra` | JSONB | nullable | extensional session metadata |
| `created_at` | timestamptz | default now, not null | creation time |
| `updated_at` | timestamptz | default now, not null | last update |

### 3.5 `chat_messages`

Business meaning:

- every message within a session, including tool call metadata for assistant messages.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, not null | message ID |
| `session_id` | UUID | FK, indexed, not null | parent session |
| `role` | string(20) | indexed, not null | `user`, `assistant`, `system`, `tool` |
| `content` | text | not null | message body |
| `token_count` | integer | nullable | LLM token count |
| `model_used` | string(100) | nullable | model name |
| `tool_calls` | JSONB | nullable | structured tool call data |
| `metadata_extra` | JSONB | nullable | extra metadata |
| `created_at` | timestamptz | default now, not null | creation time |

### 3.6 `molecule_properties`

Business meaning:

- stores imported or computed property blobs per molecule and per source.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, not null | property row ID |
| `molecule_id` | UUID | FK, indexed, not null | parent molecule |
| `source` | string(50) | not null | `pubchem`, `rdkit`, `xtb`, etc. |
| `data` | JSONB | not null | property payload |
| `created_at` | timestamptz | default now, not null | creation time |

### 3.7 `molecule_structures`

Business meaning:

- stores actual structure payloads for one molecule in one or more formats and generation methods.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, not null | structure row ID |
| `molecule_id` | UUID | FK, indexed, not null | parent molecule |
| `format` | string(20) | not null | `sdf`, `mol2`, `xyz`, `pdb`, `mol` |
| `structure_data` | text | not null | raw structure content |
| `generation_method` | string(50) | not null | `pubchem`, `rdkit`, `xtb-optimized`, etc. |
| `is_primary` | boolean | not null | preferred structure for format |
| `metadata_extra` | JSONB | nullable | extra structure metadata |
| `created_at` | timestamptz | default now, not null | creation time |

### 3.8 `feedbacks`

Business meaning:

- user scoring and comments on assistant output.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, not null | feedback ID |
| `message_id` | UUID | FK, indexed, not null | target assistant message |
| `session_id` | UUID | FK, indexed, not null | parent session |
| `rating` | integer | not null | 1-5 rating |
| `category` | string(50) | indexed, nullable | feedback category |
| `comment` | text | nullable | free text comment |
| `user_identifier` | string(256) | nullable | external user marker |
| `metadata_extra` | JSONB | nullable | extra feedback metadata |
| `created_at` | timestamptz | default now, not null | creation time |

### 3.9 `molecule_card_cache` (ORM only, not migrated)

Business meaning:

- permanent cache table intended to store assembled molecule card JSON in the database.

| Field | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | cache row ID |
| `cid` | integer | unique, indexed, nullable | PubChem CID |
| `name` | string(500) | indexed, not null | display name |
| `query` | string(500) | not null | original query |
| `card_json` | JSONB | not null | full card payload |
| `created_at` | timestamptz | default now | row creation |
| `updated_at` | timestamptz | auto-updated | row update |

Status:

- defined in `backend/app/models/molecule_card.py`,
- read and written by `MoleculeOrchestrator.get_card()`,
- absent from the Alembic migration history.

## 4. Relationships Detail

| From | To | Type | FK | Cascade | Description |
|---|---|---|---|---|---|
| `sessions` | `chat_messages` | 1:N | `chat_messages.session_id` | `CASCADE` | deleting a session deletes its messages |
| `sessions` | `feedbacks` | 1:N | `feedbacks.session_id` | `CASCADE` | deleting a session deletes attached feedback |
| `chat_messages` | `feedbacks` | 1:N | `feedbacks.message_id` | `CASCADE` | deleting a message deletes its feedback |
| `molecules` | `molecule_structures` | 1:N | `molecule_structures.molecule_id` | `CASCADE` | one molecule can have many structures |
| `molecules` | `molecule_properties` | 1:N | `molecule_properties.molecule_id` | `CASCADE` | one molecule can have many property payloads |

## 5. Index Strategy

### 5.1 `api_keys`

| Index | Columns | Purpose |
|---|---|---|
| `ix_api_keys_key_hash` | `key_hash` | direct API key lookup |
| `ix_apikey_active` | `is_active` partial true | active-key filtering |

### 5.2 `audit_logs`

| Index | Columns | Purpose |
|---|---|---|
| `ix_audit_action` | `action` | action filtering |
| `ix_audit_actor` | `actor` | actor filtering |
| `ix_audit_created` | `created_at` | time-range queries |
| `ix_audit_details_gin` | `details` | JSONB search |
| `ix_audit_resource` | `resource_type, resource_id` | resource lookup |

### 5.3 `molecules`

| Index | Columns | Purpose |
|---|---|---|
| `ix_molecules_cid` | `cid` unique | direct CID lookup |
| `ix_molecules_inchikey` | `inchikey` unique | direct structure identifier lookup |
| `ix_molecules_name` | `name` | exact/prefix name search |
| `ix_molecules_name_trgm` | `name` gin_trgm | fuzzy name search |
| `ix_molecules_not_deleted` | `is_deleted` partial false | active row scans |
| `ix_molecules_properties_gin` | `properties` gin | metadata querying |
| `ix_molecules_search_vector` | `search_vector` gin | full-text search |

### 5.4 `sessions`

| Index | Columns | Purpose |
|---|---|---|
| `ix_sessions_user_identifier` | `user_identifier` | user-scoped session filtering |

### 5.5 `chat_messages`

| Index | Columns | Purpose |
|---|---|---|
| `ix_chat_messages_session_id` | `session_id` | session message fetch |
| `ix_chatmsg_role` | `role` | role-based filtering |
| `ix_chatmsg_session_created` | `session_id, created_at` | ordered history retrieval |
| `ix_chatmsg_tool_calls_gin` | `tool_calls` gin | tool-call metadata search |

### 5.6 `molecule_properties`

| Index | Columns | Purpose |
|---|---|---|
| `ix_molecule_properties_molecule_id` | `molecule_id` | parent lookup |
| `ix_molprop_data_gin` | `data` gin | property blob querying |
| `ix_molprop_mol_source` | `molecule_id, source` | source-specific property lookup |

### 5.7 `molecule_structures`

| Index | Columns | Purpose |
|---|---|---|
| `ix_molecule_structures_molecule_id` | `molecule_id` | parent lookup |
| `ix_molstruct_mol_format` | `molecule_id, format` | format retrieval |
| `uq_mol_struct_primary` | `molecule_id, format, is_primary` | prevents duplicate primary flag combinations |

### 5.8 `feedbacks`

| Index | Columns | Purpose |
|---|---|---|
| `ix_feedback_category` | `category` | category stats |
| `ix_feedback_session_rating` | `session_id, rating` | rating analytics per session |
| `ix_feedbacks_message_id` | `message_id` | per-message lookup |
| `ix_feedbacks_session_id` | `session_id` | per-session lookup |

### 5.9 Index Gaps and Risks

- `search_vector` exists, but no trigger or update mechanism was found to maintain it.
- `molecule_card_cache` indexes exist only in ORM, not in the migrated database.
- knowledge services expect vector search support, but no vector table/index is migrated.

## 6. Enum & Type Definitions

### 6.1 Message Roles

Observed values:

- `user`
- `assistant`
- `system`
- `tool`

Source:

- `backend/app/models/session.py`
- `backend/app/schemas/chat.py`

### 6.2 Molecule Structure Formats

Observed values:

- `sdf`
- `mol2`
- `xyz`
- `pdb`
- `mol`

Source:

- `backend/app/models/molecule.py`
- `backend/app/schemas/molecule.py`

### 6.3 Structure Generation Methods

Observed values from code and comments:

- `pubchem`
- `rdkit`
- `rdkit-etkdg`
- `conforge`
- `xtb-optimized`
- combined variants such as `rdkit-etkdg+xtb-gfn2`

### 6.4 Property Sources

Observed values:

- `pubchem`
- `rdkit`
- `xtb`
- `chembl`

### 6.5 Feedback Categories

Observed values:

- `accuracy`
- `helpfulness`
- `speed`
- `hallucination`
- `other`

Source:

- `backend/app/models/feedback.py`
- `backend/app/routers/feedback.py`

### 6.6 Calculation Status

Observed schema comments / API usage:

- `pending`
- `running`
- `completed`
- `failed`

Source:

- `backend/app/schemas/molecule.py`
- queue-related service code

### 6.7 Health Status Values

Observed values:

- `healthy`
- `degraded`
- `unhealthy`
- `alive`
- `ready`

## 7. Migration History & Schema Evolution

### 7.1 Migration Inventory

| Revision | File | Summary |
|---|---|---|
| `84284f870ead` | `backend/alembic/versions/20260220_1504_84284f870ead_initial_schema.py` | initial schema: auth keys, audit logs, sessions, chat, molecules, properties, structures, feedback |

### 7.2 Initial Migration Scope

The initial migration creates:

- `api_keys`
- `audit_logs`
- `molecules`
- `sessions`
- `chat_messages`
- `molecule_properties`
- `molecule_structures`
- `feedbacks`

### 7.3 Evolution Drift After Migration

Code evolved beyond the migrated schema:

- `MoleculeCardCache` model added but never migrated.
- knowledge indexing services were added but no `knowledge_chunks` table migration exists.
- comments imply partitioning strategy for audit and chat tables, but only comments exist in ORM and migration text; no partition DDL beyond notes is visible in this repo state.

## 8. Data Flow Diagram

### 8.1 Chat Data Flow

```text
User message
  -> router/chat.py
  -> session resolved/created
  -> agent invoked
  -> user message saved to chat_messages
  -> assistant message saved to chat_messages
  -> session.message_count incremented
  -> response returned
```

### 8.2 Molecule Search Data Flow

```text
search query
  -> router/molecules.py:/search
  -> QueryResolver
  -> cache lookup
  -> federated provider search
  -> molecule rows persisted/updated
  -> response schema built
  -> frontend cards rendered
```

### 8.3 Molecule Detail / Structure Flow

```text
molecule UUID
  -> get_detail()
  -> cache lookup
  -> molecules + structures + properties read
  -> optional L1/L2 enrichment
  -> available_formats derived
  -> detail response returned
```

### 8.4 Molecule Card Flow

```text
card query or CID
  -> get_card()
  -> Redis card cache
  -> DB card cache attempt
  -> PubChem direct or search fallback
  -> GHS, similarity, AI summary, drug-likeness
  -> Redis save
  -> DB save attempt to molecule_card_cache
  -> response returned
```

### 8.5 Calculation Flow

```text
POST /calculate
  -> queue submission in Redis
  -> worker.py consumes task
  -> xTB runner executes calculation
  -> status stored back to Redis
  -> GET /calculations/{task_id} polls result
```

## 9. Data Layer Issues Worth Knowing

| Issue | Evidence | Impact |
|---|---|---|
| `molecule_card_cache` not migrated | model exists, migration absent | runtime DB cache path may fail |
| `knowledge_chunks` missing | knowledge services reference it | RAG/indexing subsystem unusable |
| `search_vector` maintenance missing | no trigger/update path found | local full-text search quality may degrade |
| mixed `Base` imports in models | `molecule_card.py` vs others | metadata/Alembic consistency risk |

---
# 📄 DOCUMENT 3 — API_REFERENCE.md

## 1. API Overview

### 1.1 Base URLs

| Context | Base |
|---|---|
| Backend router prefix | `/api/v1` |
| Health public path | `/api/v1/health` |
| WebSocket | `/ws/chat/{session_id}` |
| Frontend base path | `/molchat` |

### 1.2 Versioning Strategy

- HTTP API uses path versioning through `/api/v1`.
- WebSocket path is not versioned.
- The repository does not implement parallel `/v2` or header-based versioning.

### 1.3 Authentication Strategy

Nominal backend strategy:

- `X-API-Key` header support,
- JWT bearer token support,
- public routes limited to health/docs/metrics/search,
- all other routes are protected by middleware.

Important implementation caveat:

- in `APP_ENV=development`, the auth middleware allows unauthenticated requests through,
- the active frontend does not attach auth headers,
- therefore local development behavior is not representative of production enforcement.

### 1.4 Common Response Envelopes

Success examples:

- `SuccessResponse`
- schema-specific JSON body
- plain text for structure download and SDF generation
- SSE stream for `/chat/stream`
- WebSocket JSON events for `/ws/chat/{session_id}`

Error example shape:

```json
{
  "error": "MOLECULE_NOT_FOUND",
  "message": "Molecule not found: aspirin123",
  "status": 404,
  "details": {
    "query": "aspirin123"
  },
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

## 2. Authentication & Authorization

### 2.1 Authentication Flow Diagram

```text
Request
  -> RequestId middleware
  -> ErrorHandler middleware
  -> RateLimiter middleware
  -> Auth middleware
      -> if path public: allow
      -> else if X-API-Key valid: allow
      -> else if Bearer JWT valid: allow
      -> else if APP_ENV=development and no creds: allow
      -> else reject
  -> router handler
```

### 2.2 Token Format

| Mechanism | Format | Source |
|---|---|---|
| API key | `X-API-Key: <raw key>` | `backend/app/core/security.py` |
| JWT | `Authorization: Bearer <jwt>` | `backend/app/core/security.py` |

### 2.3 Token Expiry Policy

| Item | Value |
|---|---|
| JWT algorithm | `HS256` |
| JWT access token expiry default | `60` minutes |
| JWT issuance endpoint | not found in repo |
| Refresh token support | not found in repo |

### 2.4 Authorization Model

Observed model:

- authentication gate only,
- no role table,
- no permission matrix,
- no RBAC decorators,
- no per-resource ACL system.

### 2.5 Permission Matrix

| Route Class | Public | Authenticated | Role Enforcement |
|---|---|---|---|
| health | yes | optional | none |
| molecule search | yes | optional | none |
| chat/session/feedback/detail/card/calc | no outside development | yes | none |
| docs/openapi/metrics | yes | optional | none |

## 3. Common Conventions

### 3.1 HTTP Status Code Usage

| Code | Typical Use |
|---|---|
| `200` | successful fetch or command |
| `201` | create feedback or create session |
| `204` | delete session in chat router |
| `400` | missing required query/body parameter |
| `401` | missing or invalid auth outside development |
| `403` | not explicitly used by current routers |
| `404` | missing session, message, molecule, or structure |
| `422` | invalid SMILES or validation failures |
| `429` | rate limit exceeded |
| `500` | generation failure or internal server error |
| `502` | chat upstream LLM error path |
| `503` | readiness probe dependency failure |

### 3.2 Pagination Pattern

Observed patterns:

- `limit` + `offset`
- session list uses `total`, `limit`, `offset`, `sessions`
- molecule search uses `total`, `limit`, `offset`, `results`
- no cursor pagination found

### 3.3 Filtering and Sorting

Observed query parameter conventions:

- free text search via `q`
- source filter via comma-separated `sources`
- explicit toggles like `include_calculation`
- router-side default sort by `updated_at desc` or `created_at desc`

### 3.4 Error Response Schema

Primary unified schema:

- `error`
- `message`
- `status`
- `details`
- `request_id`

### 3.5 Middleware Pipeline

Registration code adds middleware in this order:

1. CORS helper
2. `AuthMiddleware`
3. `RateLimiterMiddleware`
4. `ErrorHandlerMiddleware`
5. `RequestIdMiddleware`

Module comment states intended effective request flow as:

1. `RequestIdMiddleware`
2. `ErrorHandlerMiddleware`
3. `RateLimiterMiddleware`
4. `AuthMiddleware`

Both facts matter because debugging order in Starlette-style middleware can be non-obvious.

## 4. Endpoint Catalog

### [GET] `/api/v1/health`

- Description: full dependency health check for DB, Redis, LLMs, and queue.
- Authentication: Public
- Permission: none
- Request Headers: none
- Path Parameters: none
- Query Parameters: none
- Request Body: none
- Response 200 example:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "environment": "development",
  "checks": {
    "database": {"status": "healthy", "type": "postgresql"},
    "cache": {"status": "healthy", "type": "redis"},
    "ollama": {"status": "healthy"},
    "gemini": {"status": "healthy"},
    "calculation_queue": {"status": "healthy"}
  },
  "elapsed_ms": 45.2
}
```
- Error Responses: `500` internal health-check failure path if middleware catches unexpected exceptions.

### [GET] `/api/v1/health/live`

- Description: lightweight liveness probe.
- Authentication: Public
- Permission: none
- Request Headers: none
- Path Parameters: none
- Query Parameters: none
- Request Body: none
- Response 200 example:
```json
{"status": "alive"}
```
- Error Responses: not expected in normal path.

### [GET] `/api/v1/health/ready`

- Description: readiness probe that checks DB and Redis only.
- Authentication: Public
- Permission: none
- Request Headers: none
- Path Parameters: none
- Query Parameters: none
- Request Body: none
- Response 200 example:
```json
{"status": "ready"}
```
- Error Responses:
  - `503` when DB or Redis is unavailable.

### [POST] `/api/v1/feedback`

- Description: submit feedback on a chat message.
- Authentication: Required outside development
- Permission: none
- Request Headers: `Content-Type: application/json`
- Path Parameters: none
- Query Parameters: none
- Request Body:
```json
{
  "message_id": "uuid",
  "session_id": "uuid",
  "rating": 5,
  "category": "accuracy",
  "comment": "Helpful answer"
}
```
- Response 201 example:
```json
{
  "success": true,
  "message": "Feedback submitted successfully",
  "timestamp": "2026-03-28T00:00:00Z"
}
```
- Error Responses:
  - `404` target message not found
  - `401` auth failure outside development
  - `422` validation failure
  - `500` unexpected persistence failure

### [GET] `/api/v1/feedback/stats`

- Description: aggregated feedback statistics.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters: none
- Query Parameters: none
- Request Body: none
- Response 200 example:
```json
{
  "total_feedbacks": 12,
  "average_rating": 4.25,
  "rating_distribution": {"4": 4, "5": 8},
  "category_distribution": {"accuracy": 6, "helpfulness": 6},
  "recent_comments": []
}
```
- Error Responses:
  - `401` auth failure outside development
  - `500` aggregation failure

### [GET] `/api/v1/feedback/{session_id}`

- Description: list feedback items for one session.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters:
  - `session_id`: UUID
- Query Parameters: none
- Request Body: none
- Response 200 example:
```json
[
  {
    "id": "uuid",
    "message_id": "uuid",
    "session_id": "uuid",
    "rating": 4,
    "category": "helpfulness",
    "comment": "Good",
    "created_at": "2026-03-28T00:00:00+00:00"
  }
]
```
- Error Responses:
  - `401` auth failure outside development
  - `422` invalid UUID
  - `500` query failure

### [POST] `/api/v1/sessions`

- Description: create a new chat session.
- Authentication: Required outside development
- Permission: none
- Request Headers: `Content-Type: application/json`
- Path Parameters: none
- Query Parameters: none
- Request Body:
```json
{
  "title": "My chemistry chat",
  "model_preference": "gemini-2.5-flash"
}
```
- Response 201 example:
```json
{
  "id": "uuid",
  "title": "My chemistry chat",
  "model_used": "gemini-2.5-flash",
  "message_count": 0,
  "created_at": "2026-03-28T00:00:00+00:00",
  "updated_at": "2026-03-28T00:00:00+00:00"
}
```
- Error Responses:
  - `401` auth failure outside development
  - `422` validation failure
  - `500` create failure

### [GET] `/api/v1/sessions`

- Description: list sessions with pagination.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters: none
- Query Parameters:
| Param | Type | Required | Default | Description |
|---|---|---:|---|---|
| `limit` | integer | no | `20` | page size |
| `offset` | integer | no | `0` | page offset |
- Request Body: none
- Response 200 example:
```json
{
  "total": 4,
  "limit": 20,
  "offset": 0,
  "sessions": []
}
```
- Error Responses:
  - `401` auth failure outside development
  - `422` invalid pagination values
  - `500` query failure

### [GET] `/api/v1/sessions/{session_id}`

- Description: fetch one session summary.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters:
  - `session_id`: UUID
- Query Parameters: none
- Request Body: none
- Response 200 example: one `SessionResponse`
- Error Responses:
  - `404` session not found
  - `401` auth failure outside development
  - `422` invalid UUID

### [PATCH] `/api/v1/sessions/{session_id}`

- Description: update session title or model preference.
- Authentication: Required outside development
- Permission: none
- Request Headers: `Content-Type: application/json`
- Path Parameters:
  - `session_id`: UUID
- Query Parameters: none
- Request Body:
```json
{
  "title": "Renamed session",
  "model_preference": "qwen3:32b"
}
```
- Response 200 example: updated `SessionResponse`
- Error Responses:
  - `404` session not found
  - `401` auth failure outside development
  - `422` validation failure

### [DELETE] `/api/v1/sessions/{session_id}`

- Description: delete a session and its messages.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters:
  - `session_id`: UUID
- Query Parameters: none
- Request Body: none
- Response 200 example:
```json
{
  "success": true,
  "message": "Session deleted successfully",
  "timestamp": "2026-03-28T00:00:00Z"
}
```
- Error Responses:
  - `404` session not found
  - `401` auth failure outside development
  - `422` invalid UUID

### [POST] `/api/v1/chat`

- Description: send a message and receive a completed AI answer.
- Authentication: Required outside development
- Permission: none
- Request Headers: `Content-Type: application/json`
- Path Parameters: none
- Query Parameters: none
- Request Body:
```json
{
  "message": "Tell me about caffeine",
  "session_id": "uuid-or-null",
  "context": null,
  "stream": false
}
```
- Response 200 example:
```json
{
  "session_id": "uuid",
  "message": {
    "id": "uuid",
    "session_id": "uuid",
    "role": "assistant",
    "content": "Caffeine is ...",
    "token_count": 123,
    "model_used": "gemini-2.5-flash",
    "tool_calls": null,
    "metadata_extra": null,
    "created_at": "2026-03-28T00:00:00+00:00"
  },
  "molecules_referenced": [],
  "tool_results": [],
  "confidence": 0.83,
  "hallucination_flags": [],
  "elapsed_ms": 1543.2
}
```
- Error Responses:
  - `401` auth failure outside development
  - `422` invalid request payload
  - `502` all LLM providers failed
  - `500` persistence or orchestration failure

### [POST] `/api/v1/chat/stream`

- Description: stream chat output as server-sent events.
- Authentication: Required outside development
- Permission: none
- Request Headers:
  - `Content-Type: application/json`
  - `Accept: text/event-stream`
- Path Parameters: none
- Query Parameters: none
- Request Body: same as `/api/v1/chat`
- Response 200:
```text
event: token
data: {"type":"token","data":"partial text"}
```
- Error Responses:
  - `401` auth failure outside development
  - `422` validation failure
  - `500` stream failure

### [GET] `/api/v1/chat/{session_id}/history`

- Description: fetch ordered conversation history for a session.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters:
  - `session_id`: UUID
- Query Parameters:
| Param | Type | Required | Default | Description |
|---|---|---:|---|---|
| `limit` | integer | no | `50` | max messages |
| `offset` | integer | no | `0` | offset from newest query |
- Request Body: none
- Response 200: array of `ChatMessageResponse`
- Error Responses:
  - `401` auth failure outside development
  - `422` invalid UUID or pagination
  - `500` query failure

### [GET] `/api/v1/chat/sessions`

- Description: list sessions from the chat router with optional search.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters: none
- Query Parameters:
| Param | Type | Required | Default | Description |
|---|---|---:|---|---|
| `q` | string | no | `null` | title or message-content search |
| `limit` | integer | no | `50` | page size |
| `offset` | integer | no | `0` | page offset |
- Request Body: none
- Response 200: `SessionListResponse`
- Error Responses:
  - `401` auth failure outside development
  - `422` invalid pagination
  - `500` query failure

### [GET] `/api/v1/chat/sessions/{session_id}`

- Description: fetch one session summary from the duplicate chat-router CRUD surface.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters:
  - `session_id`: UUID
- Query Parameters: none
- Request Body: none
- Response 200: `SessionResponse`
- Error Responses:
  - `404` session not found
  - `401` auth failure outside development
  - `422` invalid UUID

### [PUT] `/api/v1/chat/sessions/{session_id}`

- Description: update session title through the duplicate chat-router CRUD surface.
- Authentication: Required outside development
- Permission: none
- Request Headers: `Content-Type: application/json`
- Path Parameters:
  - `session_id`: UUID
- Query Parameters: none
- Request Body:
```json
{"title": "Renamed from chat router"}
```
- Response 200: updated `SessionResponse`
- Error Responses:
  - `404` session not found
  - `401` auth failure outside development
  - `422` validation failure

### [DELETE] `/api/v1/chat/sessions/{session_id}`

- Description: delete a session through the duplicate chat-router CRUD surface.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters:
  - `session_id`: UUID
- Query Parameters: none
- Request Body: none
- Response 204: no body
- Error Responses:
  - `404` session not found
  - `401` auth failure outside development
  - `422` invalid UUID
### [POST] `/api/v1/molecules/generate-3d`

- Description: generate a 3D structure from SMILES.
- Authentication: Required outside development
- Permission: none
- Request Headers: `Content-Type: application/json`
- Path Parameters: none
- Query Parameters: none
- Request Body:
```json
{
  "smiles": "Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
  "name": "Caffeine",
  "format": "sdf",
  "optimize_xtb": false
}
```
- Response 200 example:
```json
{
  "smiles": "Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
  "format": "sdf",
  "structure_data": "....SDF....",
  "generation_method": "rdkit-etkdg",
  "atom_count": 24,
  "properties": {}
}
```
- Error Responses:
  - `422` invalid SMILES or atom limit exceeded
  - `500` generation failure
  - `401` auth failure outside development

### [GET] `/api/v1/molecules/generate-3d/sdf`

- Description: quick plain-text SDF generation endpoint.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters: none
- Query Parameters:
| Param | Type | Required | Default | Description |
|---|---|---:|---|---|
| `smiles` | string | yes | none | SMILES input |
| `optimize_xtb` | boolean | no | `false` | optimization toggle |
- Request Body: none
- Response 200: `text/plain` SDF payload
- Error Responses:
  - `422` invalid SMILES
  - `500` generation failure
  - `401` auth failure outside development

### [GET] `/api/v1/molecules/card`

- Description: retrieve a comprehensive molecule card.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters: none
- Query Parameters:
| Param | Type | Required | Default | Description |
|---|---|---:|---|---|
| `q` | string | conditional | `null` | name, SMILES, InChIKey, or formula |
| `cid` | integer | conditional | `null` | PubChem CID |
- Request Body: none
- Response 200 example:
```json
{
  "id": "uuid",
  "cid": 2519,
  "name": "Caffeine",
  "iupac_name": "1,3,7-trimethylpurine-2,6-dione",
  "canonical_smiles": "Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
  "molecular_formula": "C8H10N4O2",
  "molecular_weight": 194.19,
  "drug_likeness": [],
  "similar_molecules": [],
  "ai_summary": "..."
}
```
- Error Responses:
  - `400` both `q` and `cid` missing
  - `401` auth failure outside development
  - `404` unresolved molecule
  - `500` orchestration/cache failure

### [GET] `/api/v1/molecules/search`

- Description: search across local and external molecule sources.
- Authentication: Public
- Permission: none
- Request Headers: none
- Path Parameters: none
- Query Parameters:
| Param | Type | Required | Default | Description |
|---|---|---:|---|---|
| `q` | string | yes | none | query text |
| `limit` | integer | no | `10` | max results |
| `offset` | integer | no | `0` | page offset |
| `sources` | string | no | `null` | comma-separated source names |
- Request Body: none
- Response 200 example:
```json
{
  "query": "caffeine",
  "total": 1,
  "limit": 10,
  "offset": 0,
  "results": [],
  "sources_queried": ["local", "pubchem"],
  "cache_hit": false,
  "elapsed_ms": 312.4
}
```
- Error Responses:
  - `404` no molecule found
  - `422` invalid query or pagination
  - `500` provider failure

### [GET] `/api/v1/molecules/resolve`

- Description: resolve comma-separated names to PubChem CIDs.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters: none
- Query Parameters:
| Param | Type | Required | Default | Description |
|---|---|---:|---|---|
| `names` | string | yes | none | comma-separated names |
- Request Body: none
- Response 200 example:
```json
{
  "resolved": [
    {"name": "Caffeine", "cid": 2519}
  ],
  "total": 1
}
```
- Error Responses:
  - `401` auth failure outside development
  - `422` missing query parameter
  - `500` upstream resolution failure path

### [GET] `/api/v1/molecules/{molecule_id}`

- Description: fetch molecule detail by internal UUID.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters:
  - `molecule_id`: UUID
- Query Parameters:
| Param | Type | Required | Default | Description |
|---|---|---:|---|---|
| `include_calculation` | boolean | no | `false` | include calculation status |
- Request Body: none
- Response 200 example:
```json
{
  "molecule": {},
  "available_formats": ["sdf", "xyz"],
  "calculation_status": "completed",
  "related_molecules": []
}
```
- Error Responses:
  - `404` molecule not found
  - `401` auth failure outside development
  - `422` invalid UUID

### [GET] `/api/v1/molecules/{molecule_id}/structure/{fmt}`

- Description: download one molecule structure in a requested format.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters:
  - `molecule_id`: UUID
  - `fmt`: structure format
- Query Parameters: none
- Request Body: none
- Response 200: `text/plain` structure content
- Error Responses:
  - `404` molecule or convertible structure missing
  - `401` auth failure outside development
  - `422` invalid UUID
  - `500` conversion failure

### [GET] `/api/v1/molecules/{molecule_id}/structures`

- Description: list available stored structure variants for one molecule.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters:
  - `molecule_id`: UUID
- Query Parameters: none
- Request Body: none
- Response 200 example:
```json
[
  {
    "id": "uuid",
    "format": "sdf",
    "generation_method": "pubchem",
    "is_primary": true,
    "data_length": 2048
  }
]
```
- Error Responses:
  - `401` auth failure outside development
  - `422` invalid UUID
  - `500` query failure

### [POST] `/api/v1/molecules/{molecule_id}/calculate`

- Description: submit an xTB calculation for an existing molecule.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters:
  - `molecule_id`: UUID
- Query Parameters:
| Param | Type | Required | Default | Description |
|---|---|---:|---|---|
| `method` | string | no | `gfn2` | xTB method |
| `tasks` | string | no | `energy` | comma-separated task list |
- Request Body: none
- Response 200 example:
```json
{
  "task_id": "redis-task-id",
  "status": "pending"
}
```
- Error Responses:
  - `401` auth failure outside development
  - `404` molecule not found
  - `422` invalid UUID or task parameters
  - `500` queue submission failure

### [GET] `/api/v1/molecules/calculations/{task_id}`

- Description: poll the calculation queue for status.
- Authentication: Required outside development
- Permission: none
- Request Headers: optional auth headers
- Path Parameters:
  - `task_id`: string
- Query Parameters: none
- Request Body: none
- Response 200 example:
```json
{
  "task_id": "redis-task-id",
  "status": "running"
}
```
- Error Responses:
  - `401` auth failure outside development
  - `404` task missing
  - `500` queue failure

### [POST] `/api/v1/molecules/compare`

- Description: compare multiple molecules from SMILES and optional names.
- Authentication: Required outside development
- Permission: none
- Request Headers:
  - current implementation accepts body parameters directly from FastAPI model-less list parsing
- Path Parameters: none
- Query Parameters: none
- Request Body example:
```json
{
  "smiles_list": ["CCO", "CCN"],
  "names": ["ethanol", "ethylamine"]
}
```
- Response 200 example:
```json
{
  "comparison": {}
}
```
- Error Responses:
  - `401` auth failure outside development
  - `422` validation failure
  - `500` comparison logic failure

## 5. WebSocket / Real-time Events

### [WS] `/ws/chat/{session_id}`

- Description: real-time chat channel that streams token and tool events.
- Authentication: no explicit auth enforcement in the route implementation.
- Connection:
  client opens WebSocket,
  server accepts immediately,
  route creates `MolChatAgent`,
  history is kept in-memory per connection.

### 5.1 Client Message Types

| Type | Payload | Meaning |
|---|---|---|
| `message` | `{"type":"message","content":"..."}` | send user input |
| `ping` | `{"type":"ping"}` | keepalive |

### 5.2 Server Event Types

| Type | Payload | Meaning |
|---|---|---|
| `token` | partial text | stream text token |
| `tool_start` | tool metadata | tool started |
| `tool_result` | tool result metadata | tool completed |
| `done` | elapsed metadata | stream finished |
| `error` | message string | stream error |
| `pong` | none | ping response |

### 5.3 Example Exchange

```json
{"type":"message","content":"Tell me about caffeine"}
{"type":"token","data":"Caffeine"}
{"type":"token","data":" is ..."}
{"type":"done","data":{"elapsed_ms":1234}}
```

## 6. Rate Limiting & Throttling

### 6.1 Rule Set

| Setting | Default |
|---|---:|
| `RATE_LIMIT_REQUESTS` | `60` |
| `RATE_LIMIT_WINDOW` | `60` seconds |

### 6.2 Enforcement

- implemented in `backend/app/middleware/rate_limiter.py`,
- Redis-backed sliding-window set,
- applies before router execution,
- fail-open when Redis is unavailable.

### 6.3 Over-limit Behavior

- expected HTTP status: `429`
- middleware-specific error path handled by `ErrorHandlerMiddleware`
- headers are added for rate-limit context

## 7. Middleware Pipeline

### 7.1 Ordered Flow

```text
incoming request
  -> CORS handling
  -> request ID assignment
  -> error handling wrapper
  -> rate limiter
  -> auth middleware
  -> route handler
  -> response
```

### 7.2 Middleware Files

| Concern | File |
|---|---|
| registration | `backend/app/middleware/__init__.py` |
| CORS | `backend/app/middleware/cors.py` |
| request ID | `backend/app/middleware/request_id.py` |
| errors | `backend/app/middleware/error_handler.py` |
| rate limiting | `backend/app/middleware/rate_limiter.py` |
| auth | `backend/app/middleware/auth.py` |

## 8. API Surface Summary

### 8.1 HTTP Endpoint Count

- Health: `3`
- Feedback: `3`
- Sessions router: `5`
- Chat router: `7`
- Molecules router: `11`
- Total HTTP endpoints: `29`
- WebSocket endpoints: `1`

### 8.2 Important API Caveats

- Session CRUD is duplicated across `routers/sessions.py` and `routers/chat.py`.
- `molecules/search` is public; most other domain routes are nominally protected.
- The active frontend relies on development-mode auth bypass.
- Some generated documentation in the repo still claims `23` endpoints; that is not the current implementation.

---
# 📄 DOCUMENT 4 — DEVELOPMENT_SETUP.md

## 1. Prerequisites

### 1.1 Required Software

| Software | Version / Constraint | Why Needed |
|---|---|---|
| Python | `>=3.11` | backend runtime |
| Node.js | `>=20.0.0` | frontend runtime |
| npm | bundled with Node 20+ | frontend package manager |
| PostgreSQL | 16-compatible | persistent store |
| Redis | 7.2-compatible | cache, rate limit, queue |
| Ollama | current local runtime | fallback LLM path |
| Git | recent | version control |
| Conda or equivalent | recommended by scripts | backend env activation in WSL scripts |
| WSL / Linux shell | strongly implied | root scripts are Bash-first |

### 1.2 Chemistry Runtime Dependencies Not Declared Properly

These are used by code but not fully declared in `backend/pyproject.toml`:

- RDKit
- xTB executable/toolchain
- `rapidfuzz`

### 1.3 OS Notes

| OS | Status | Notes |
|---|---|---|
| Windows native | partial | frontend `next` binary issue observed in this workspace |
| WSL/Linux | primary path in scripts | `start-molchat.sh` and related files assume Bash + conda |
| macOS | possible but undocumented | no macOS-specific scripts present |

## 2. Step-by-Step Setup

### 2.1 Clone and Enter Repository

```bash
git clone <repo-url>
cd v3
```

Expected result:

- root contains `backend/`, `frontend/`, `docker-compose.yml`, and startup scripts.

### 2.2 Backend Environment

Recommended from repository conventions:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
```

Expected result:

- FastAPI and dev tooling installed,
- note that extra chemistry deps still need manual installation.

### 2.3 Frontend Environment

```bash
cd frontend
npm install
```

Expected result:

- `node_modules` present,
- `next` binary should be available.

Reality observed during scan:

- in this Windows workspace, `node_modules/.bin/next` exists as a zero-byte shim,
- `npm run build` failed with `'next' is not recognized`.

### 2.4 Configure Environment Variables

Repository does not include `.env.example`.

Use sanitized values derived from the committed env files:

- root `.env`
- `backend/.env`
- `frontend/.env.local`
- `frontend/.env.production`

Create local env files before starting services.

### 2.5 Start Supporting Services

Option A: Compose, if Dockerfiles are added/fixed.

```bash
docker compose up -d postgres redis ollama
```

Option B: run services separately on expected ports:

- Postgres host port `5433`
- Redis `6379`
- Ollama `11434`

### 2.6 Apply Database Migration

```bash
cd backend
alembic upgrade head
```

Expected result:

- the 8 migrated tables are created.

### 2.7 Start Backend

Compose expectation:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

WSL script expectation:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8333 --workers 2
```

Expected result:

- health endpoint responds at either `8000` or `8333` depending on chosen path.

### 2.8 Start Frontend

Development:

```bash
cd frontend
npm run dev
```

Production-like:

```bash
npm run build
npm start
```

Expected result:

- app is served under `/molchat` because `next.config.mjs` sets `basePath: '/molchat'`.

### 2.9 Smoke Test

Check:

- `GET /api/v1/health`
- frontend root `/molchat`
- molecule search via `/api/v1/molecules/search?q=caffeine`

## 3. Environment Variables

### 3.1 Backend Variables

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `APP_NAME` | no | `MolChat` | backend app name | `MolChat` |
| `APP_ENV` | no | `production` | environment mode | `development` |
| `APP_DEBUG` | no | `false` | debug toggle | `true` |
| `APP_VERSION` | no | `1.0.0` | app version | `1.0.0` |
| `APP_HOST` | no | `0.0.0.0` | bind host | `0.0.0.0` |
| `APP_PORT` | no | `8000` | backend port | `8000` |
| `LOG_LEVEL` | no | `INFO` | log verbosity | `DEBUG` |
| `ALLOWED_ORIGINS` | no | `http://localhost:3000` | CORS origins | `http://localhost:3000,http://localhost:3001` |
| `POSTGRES_HOST` | no | `postgres` | DB host | `localhost` |
| `POSTGRES_PORT` | no | `5432` | DB port | `5433` |
| `POSTGRES_DB` | no | `molchat` | DB name | `molchat` |
| `POSTGRES_USER` | no | `molchat` | DB user | `molchat` |
| `POSTGRES_PASSWORD` | yes in practice | empty | DB password | `<set-me>` |
| `DATABASE_URL` | conditional | assembled | async DB DSN | `postgresql+asyncpg://...` |
| `DB_POOL_SIZE` | no | `20` | SQLAlchemy pool size | `20` |
| `DB_MAX_OVERFLOW` | no | `10` | SQLAlchemy overflow | `10` |
| `DB_POOL_TIMEOUT` | no | `30` | pool wait seconds | `30` |
| `REDIS_HOST` | no | `redis` | Redis host | `localhost` |
| `REDIS_PORT` | no | `6379` | Redis port | `6379` |
| `REDIS_PASSWORD` | yes in practice | empty | Redis password | `<set-me>` |
| `REDIS_URL` | conditional | assembled | Redis DSN | `redis://:...@localhost:6379/0` |
| `REDIS_CACHE_TTL` | no | `3600` | cache TTL seconds | `3600` |
| `REDIS_MAX_MEMORY` | no | `512mb` | Redis max memory | `512mb` |
| `GEMINI_API_KEY` | optional but needed for primary LLM | empty | Gemini credential | `<set-me>` |
| `GEMINI_MODEL` | no | `gemini-2.5-flash` | Gemini model | `gemini-2.5-flash` |
| `GEMINI_MAX_TOKENS` | no | `8192` | generation cap | `8192` |
| `GEMINI_TEMPERATURE` | no | `0.3` | temperature | `0.3` |
| `GEMINI_TIMEOUT` | no | `30` | request timeout | `30` |
| `GEMINI_MONTHLY_COST_LIMIT` | no | `50.0` | cost guard | `50.0` |
| `OLLAMA_BASE_URL` | no | `http://ollama:11434` | Ollama endpoint | `http://localhost:11434` |
| `OLLAMA_MODEL_PRIMARY` | no | `qwen3:32b` | primary local model | `qwen3:32b` |
| `OLLAMA_MODEL_FALLBACK` | no | `qwen3:8b` | fallback local model | `qwen3:8b` |
| `OLLAMA_TIMEOUT` | no | `120` | Ollama timeout | `120` |
| `OLLAMA_NUM_CTX` | no | `8192` | context size | `8192` |
| `CHEMSPIDER_API_KEY` | optional | empty | ChemSpider integration key | `<set-me>` |
| `JWT_SECRET_KEY` | yes in production | insecure placeholder | JWT secret | `<set-me>` |
| `JWT_ALGORITHM` | no | `HS256` | JWT algorithm | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | no | `60` | JWT access lifetime | `60` |
| `API_KEY_HASH_ALGORITHM` | no | `sha256` | API key hashing | `sha256` |
| `XTB_WORKER_CONCURRENCY` | no | `2` | worker concurrency | `2` |
| `XTB_MAX_ATOMS` | no | `200` | xTB size limit | `200` |
| `XTB_TIMEOUT` | no | `20` | xTB timeout seconds | `20` |
| `XTB_METHOD` | no | `gfn2` | xTB method | `gfn2` |
| `RATE_LIMIT_REQUESTS` | no | `60` | requests per window | `60` |
| `RATE_LIMIT_WINDOW` | no | `60` | window seconds | `60` |
| `PROMETHEUS_ENABLED` | no | `true` | metrics toggle | `true` |

### 3.2 Frontend Variables

| Variable | Required | Default / Observed | Description | Example |
|---|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | yes in practice | `/molchat` in local env files | API base path | `/molchat` |
| `NEXT_PUBLIC_WS_URL` | yes in practice | `/molchat` in local env files | WebSocket base path | `/molchat` |
| `NEXT_PUBLIC_APP_NAME` | no | `MolChat` | UI app name | `MolChat` |

### 3.3 Sanitized `.env.example` Equivalent

Repository status:

- no actual `.env.example` file was found.
- the following sanitized content is derived from the real env files and config defaults.

```env
APP_NAME=MolChat
APP_ENV=development
APP_DEBUG=false
APP_VERSION=1.0.0
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO
ALLOWED_ORIGINS=http://localhost:3000

POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_DB=molchat
POSTGRES_USER=molchat
POSTGRES_PASSWORD=<set-me>
DATABASE_URL=postgresql+asyncpg://molchat:<set-me>@localhost:5433/molchat

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=<set-me>
REDIS_URL=redis://:<set-me>@localhost:6379/0
REDIS_CACHE_TTL=3600
REDIS_MAX_MEMORY=512mb

GEMINI_API_KEY=<set-me>
GEMINI_MODEL=gemini-2.5-flash
GEMINI_MAX_TOKENS=8192
GEMINI_TEMPERATURE=0.3
GEMINI_TIMEOUT=30
GEMINI_MONTHLY_COST_LIMIT=50.0

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL_PRIMARY=qwen3:32b
OLLAMA_MODEL_FALLBACK=qwen3:8b
OLLAMA_TIMEOUT=120
OLLAMA_NUM_CTX=8192

CHEMSPIDER_API_KEY=

JWT_SECRET_KEY=<set-me>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
API_KEY_HASH_ALGORITHM=sha256

XTB_WORKER_CONCURRENCY=2
XTB_MAX_ATOMS=200
XTB_TIMEOUT=20
XTB_METHOD=gfn2

RATE_LIMIT_REQUESTS=60
RATE_LIMIT_WINDOW=60
PROMETHEUS_ENABLED=true

NEXT_PUBLIC_API_URL=/molchat
NEXT_PUBLIC_WS_URL=/molchat
NEXT_PUBLIC_APP_NAME=MolChat
```

## 4. Database Setup

### 4.1 Local Database Bootstrap

Create a PostgreSQL database compatible with:

- host `localhost`
- port `5433`
- database `molchat`
- user `molchat`

### 4.2 Migration Command

```bash
cd backend
alembic upgrade head
```

### 4.3 Seed Data

No dedicated seed script was found in the repository.

Expected data sources at runtime:

- chat sessions are created through API use,
- molecules are populated lazily through search and detail flows,
- feedback is populated by user actions,
- API keys would need manual insertion unless separate tooling exists outside the repo.

### 4.4 Schema Caveats

- migrating the repo only creates the 8 tables from the initial migration.
- it does not create `molecule_card_cache`.
- it does not create `knowledge_chunks`.

## 5. Available Scripts

### 5.1 Frontend `package.json` Scripts

| Command | Description | When To Use |
|---|---|---|
| `npm run dev` | Next.js dev server with turbo | frontend development |
| `npm run build` | production build | pre-release validation |
| `npm run start` | start production server | production-like run |
| `npm run lint` | Next lint | code quality check |
| `npm run lint:fix` | lint autofix | style cleanup |
| `npm run type-check` | `tsc --noEmit` | TS validation |
| `npm run format` | prettier write | formatting |
| `npm run format:check` | prettier check | CI-style verification |

### 5.2 Root Bash Scripts

| Script | Description | When To Use |
|---|---|---|
| `deploy.sh` | mutates frontend config and startup scripts for path deployment | one-off deployment prep |
| `start-all.sh` | starts backend then frontend | simple combined run |
| `start-backend.sh` | starts backend on `8333` | local backend run |
| `start-frontend.sh` | writes `.env.local`, builds, starts frontend | local frontend run |
| `start-molchat.sh` | WSL-oriented all-in-one startup and verification | preferred scripted local run |
| `stop-all.sh` | kills ports `8333` and `3000` | cleanup |

### 5.3 Backend Scripts

No `Makefile`, `Taskfile`, or backend shell script directory was found.

## 6. IDE Configuration

### 6.1 Recommended Editor

- Visual Studio Code is the most natural fit given TypeScript, Next.js, Python, and Bash in one repo.

### 6.2 Recommended Extensions

| Extension | Why |
|---|---|
| Python | Python editing/debugging |
| Pylance | typing and import analysis |
| Ruff | backend linting |
| TypeScript and JavaScript Language Features | TS/React support |
| ESLint | frontend linting |
| Prettier | formatting |
| Tailwind CSS IntelliSense | utility class editing |
| Docker | compose visibility |
| GitLens | history on drift-heavy files |

### 6.3 Debugger Setup Guidance

Suggested backend launch target:

```json
{
  "name": "MolChat Backend",
  "type": "python",
  "request": "launch",
  "module": "uvicorn",
  "args": ["app.main:app", "--reload", "--port", "8333"],
  "cwd": "${workspaceFolder}/backend"
}
```

Suggested frontend launch target:

```json
{
  "name": "MolChat Frontend",
  "type": "node-terminal",
  "request": "launch",
  "command": "npm run dev",
  "cwd": "${workspaceFolder}/frontend"
}
```

### 6.4 Formatter/Linter Automation

- backend: `ruff` and optionally `mypy`
- frontend: `prettier`, `eslint`, `tsc --noEmit`

## 7. Docker Development

### 7.1 Compose Services

| Service | Image / Build | Port | Purpose |
|---|---|---:|---|
| `postgres` | `postgres:16-alpine` | `5433` host | database |
| `redis` | `redis:7.2-alpine` | `6379` | cache/queue |
| `ollama` | `ollama/ollama:latest` | `11434` | local LLM |
| `api` | build `./backend/Dockerfile` | `8000` | FastAPI app |
| `xtb-worker` | build `./backend/Dockerfile.xtb` | none | worker |
| `frontend` | build `./frontend/Dockerfile` | `3000` | Next.js app |

### 7.2 Compose Reality Check

The compose file is not currently runnable from this repository alone because:

- `backend/Dockerfile` is missing,
- `backend/Dockerfile.xtb` is missing,
- `frontend/Dockerfile` is missing.

### 7.3 Volume Map

| Volume | Purpose |
|---|---|
| `pg-data` | PostgreSQL data |
| `redis-data` | Redis persistence |
| `ollama-models` | downloaded Ollama models |
| `mol-cache` | molecule cache files |

## 8. Troubleshooting

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `next is not recognized` during `npm run build` | broken Windows shim in `node_modules/.bin/next` | reinstall frontend dependencies on the target OS; ensure `next.cmd` exists on Windows |
| frontend pathing breaks under `/molchat` | basePath + hardcoded routes drift | audit links and API base paths against `frontend/next.config.mjs` |
| compose build fails immediately | referenced Dockerfiles missing | add the Dockerfiles or avoid compose for now |
| backend search crashes on `rapidfuzz` import | dependency not declared/installed | install `rapidfuzz` manually or add it to `pyproject.toml` |
| structure generation fails although backend starts | RDKit or xTB runtime missing | install chemistry toolchain separately; they are not fully declared in backend deps |
| non-public routes work locally but fail in prod | dev-mode auth bypass masks missing auth headers | send `X-API-Key` or Bearer JWT in real deployments |
| molecule card DB cache path fails | `molecule_card_cache` table not migrated | add Alembic migration for the cache table |
| knowledge indexing code errors on missing table | `knowledge_chunks` never migrated | either migrate the table or disable the subsystem |
| frontend build fails in molecule detail page | malformed JSX in `frontend/src/app/molecule/[id]/page.tsx` | fix the broken `</span>` markup before building |

## 9. Directory Structure Guide

### 9.1 Top-Level Tree

```text
v3/
├── backend/                  # FastAPI backend and Alembic
├── frontend/                 # Next.js frontend
├── docker-compose.yml        # intended local/prod stack
├── deploy.sh                 # deployment mutation script
├── start-*.sh                # startup helpers
├── README.md                 # top-level docs
├── MOLCHAT_API_SPEC_V3.md    # large historical spec/source archive
├── V3명세서.md               # architecture notes
└── 개발계획.md               # refactor plan
```

### 9.2 Backend Tree Guide

```text
backend/
├── alembic/                  # migrations
├── app/
│   ├── core/                 # settings, db, redis, logging, security
│   ├── middleware/           # request pipeline concerns
│   ├── models/               # SQLAlchemy models
│   ├── routers/              # HTTP/WebSocket API
│   ├── schemas/              # Pydantic contracts
│   └── services/             # business logic
```

### 9.3 Frontend Tree Guide

```text
frontend/
├── public/js/                # vendor 3Dmol asset
├── src/app/                  # Next.js routes
├── src/components/           # reusable UI
├── src/hooks/                # React hooks
├── src/lib/                  # API client/runtime helpers
├── src/stores/               # Zustand stores
├── src/styles/               # shared CSS
└── src/types/                # TS types
```

### 9.4 “Where Should a New File Go?”

| Need | Place |
|---|---|
| new API route | `backend/app/routers/` |
| new request/response schema | `backend/app/schemas/` |
| new DB model | `backend/app/models/` |
| new backend cross-cutting concern | `backend/app/core/` or `backend/app/middleware/` |
| new molecule business logic | `backend/app/services/molecule_engine/` |
| new LLM/tool logic | `backend/app/services/intelligence/` |
| new frontend page | `frontend/src/app/` |
| new frontend reusable widget | `frontend/src/components/` |
| new frontend global state | `frontend/src/stores/` |
| new frontend API helper | `frontend/src/lib/` |

## 10. Development Reality Notes

- The repo is currently closer to a working research application than a polished production starter.
- Startup scripts are WSL-specific and more aligned with current runnable behavior than Compose.
- Documentation in `README.md` overstates test and CI maturity.
- Secret-bearing `.env` files are committed and must be sanitized before broader sharing.

---
# 📄 DOCUMENT 5 — PROJECT_CONTEXT.md

## 1. One-Paragraph Summary

MolChat v3 is a full-stack chemistry chat application built from a FastAPI backend and a Next.js frontend. The backend stores chat sessions, messages, molecules, structures, properties, feedback, and API keys in PostgreSQL, uses Redis for cache/rate limiting/queue state, queries external chemistry providers such as PubChem and ChEMBL, and routes LLM requests through Gemini with Ollama fallback. The frontend exposes a chat UI and molecule detail views, but the active `/chat` page currently bypasses some shared store abstractions and contains significant inline orchestration logic. The repository is modular enough to navigate quickly, but it contains real deployment drift, missing migrations for some active models, and a few high-risk runtime defects.

## 2. Tech Stack Quick Reference

| Layer | Technology | Version | Config File |
|---|---|---:|---|
| Backend language | Python | 3.11+ | `backend/pyproject.toml` |
| Frontend language | TypeScript | 5.6+ | `frontend/package.json`, `frontend/tsconfig.json` |
| Backend framework | FastAPI | `>=0.115` | `backend/pyproject.toml` |
| Frontend framework | Next.js | `^14.2.0` | `frontend/package.json`, `frontend/next.config.mjs` |
| UI runtime | React | `^18.3.0` | `frontend/package.json` |
| ORM | SQLAlchemy async | `>=2.0.36` | `backend/pyproject.toml` |
| Migrations | Alembic | `>=1.14.0` | `backend/pyproject.toml` |
| DB driver | asyncpg | `>=0.30.0` | `backend/pyproject.toml` |
| Cache/queue | Redis | `>=5.2.0` client | `backend/pyproject.toml`, `docker-compose.yml` |
| Cloud LLM | google-genai | `>=1.0.0` | `backend/pyproject.toml` |
| Local LLM | Ollama | external runtime | `docker-compose.yml` |
| Styling | Tailwind CSS | `^3.4.0` | `frontend/tailwind.config.ts` |
| State | Zustand | `^5.0.0` | `frontend/package.json` |
| 3D viewer | 3Dmol | `^2.4.0` | `frontend/package.json` |

## 3. Architecture at a Glance

### 3.1 Five-Line Summary

- Next.js serves the UI under `/molchat`.
- The frontend calls FastAPI routes under `/api/v1` and one WebSocket path.
- `MolChatAgent` handles conversational AI and tool usage.
- `MoleculeOrchestrator` handles molecule search, detail, card, and calculation flows.
- PostgreSQL stores durable data; Redis supports cache, rate limit, and queued work.

### 3.2 Core Layer Diagram

```text
frontend UI
  -> frontend lib/api.ts
  -> backend routers
  -> backend services
  -> Postgres / Redis / external APIs
```

## 4. Core Business Logic Map

| Module | Path | Purpose | Key Dependencies |
|---|---|---|---|
| chat route | `backend/app/routers/chat.py` | chat request handling, persistence, streaming | DB session, `MolChatAgent` |
| molecule route | `backend/app/routers/molecules.py` | search/detail/card/structure/calc endpoints | orchestrator, RDKit helpers, Redis |
| MolChat agent | `backend/app/services/intelligence/agent.py` | LLM conversation loop with tool calls | fallback router, prompt builder, tools |
| fallback router | `backend/app/services/intelligence/fallback_router.py` | Gemini -> Ollama routing | Gemini client, Ollama client |
| prompt builder | `backend/app/services/intelligence/prompt_builder.py` | chemistry system prompt | history/context formatting |
| molecule orchestrator | `backend/app/services/molecule_engine/orchestrator.py` | central molecule workflows | cache manager, search aggregator, queue |
| query resolver | `backend/app/services/molecule_engine/query_resolver.py` | normalize search query type | PubChem resolver, LLM fallback |
| search aggregator | `backend/app/services/molecule_engine/layer0_search/aggregator.py` | federated provider search | PubChem, ChEMBL, ChemSpider, ZINC, local DB |
| task queue | `backend/app/services/molecule_engine/layer2_calculation/task_queue.py` | queue calculation tasks | Redis |
| active chat page | `frontend/src/app/chat/page.tsx` | active chat UX, molecule parsing, card fetch | `frontend/src/lib/api.ts`, `MoleculeCardFull`, `MoleculePanel` |

## 5. Critical Code Paths

### 5.1 Path 1: Standard Chat Answer

Trigger:

- user sends a message from `/chat`.

Execution chain:

- `frontend/src/app/chat/page.tsx`
- `frontend/src/lib/api.ts`
- `backend/app/routers/chat.py:chat`
- `backend/app/services/intelligence/agent.py:chat`
- `backend/app/services/intelligence/fallback_router.py`
- `backend/app/services/intelligence/tools/*`
- persistence back in `routers/chat.py`

Output:

- `ChatResponse` with assistant message, tool results, confidence, molecule references.

### 5.2 Path 2: Streaming Chat

Trigger:

- frontend calls `/api/v1/chat/stream` or opens WebSocket.

Execution chain:

- `frontend/src/lib/api.ts` or `frontend/src/lib/websocket.ts`
- `backend/app/routers/chat.py:chat_stream`
- `MolChatAgent.chat_stream()`
- token/tool event stream

Output:

- streamed tokens and final saved assistant message.

### 5.3 Path 3: Molecule Search

Trigger:

- user searches by name/identifier.

Execution chain:

- `frontend/src/lib/api.ts:searchMolecules`
- `backend/app/routers/molecules.py:search_molecules`
- `backend/app/services/molecule_engine/orchestrator.py:search`
- `query_resolver.py`
- `layer0_search/aggregator.py`
- provider modules

Output:

- paginated `MoleculeSearchResponse`.

### 5.4 Path 4: Molecule Card

Trigger:

- frontend requests `getMoleculeCard`.

Execution chain:

- `frontend/src/components/molecule/MoleculeCardFull.tsx`
- `frontend/src/lib/api.ts:getMoleculeCard`
- `backend/app/routers/molecules.py:get_molecule_card`
- `backend/app/services/molecule_engine/orchestrator.py:get_card`
- Redis -> DB cache -> PubChem/search fallback -> GHS/drug-likeness/AI summary

Output:

- comprehensive `MoleculeCardResponse`.

### 5.5 Path 5: Structure Generation / Download

Trigger:

- user opens molecule detail or requests SDF.

Execution chain:

- `frontend/src/app/molecule/[id]/page.tsx`
- `frontend/src/lib/api.ts`
- `backend/app/routers/molecules.py:generate_3d_from_smiles` or `get_structure`
- `layer1_structure/rdkit_handler.py`
- `layer1_structure/conforge_handler.py`
- optional `layer2_calculation/xtb_runner.py`

Output:

- structure content or downloadable format.

## 6. Data Model Summary

### 6.1 Compressed ERD

```text
sessions -> chat_messages -> feedbacks
sessions -> feedbacks
molecules -> molecule_structures
molecules -> molecule_properties
api_keys
audit_logs
```

### 6.2 Important Non-Migrated Drift

```text
molecule_card_cache  (ORM only)
knowledge_chunks     (service expectation only)
```

## 7. API Surface Summary

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health` | full health |
| GET | `/api/v1/health/live` | liveness |
| GET | `/api/v1/health/ready` | readiness |
| POST | `/api/v1/feedback` | submit feedback |
| GET | `/api/v1/feedback/stats` | feedback analytics |
| GET | `/api/v1/feedback/{session_id}` | session feedback |
| POST | `/api/v1/sessions` | create session |
| GET | `/api/v1/sessions` | list sessions |
| GET | `/api/v1/sessions/{session_id}` | session detail |
| PATCH | `/api/v1/sessions/{session_id}` | update session |
| DELETE | `/api/v1/sessions/{session_id}` | delete session |
| POST | `/api/v1/chat` | completed chat response |
| POST | `/api/v1/chat/stream` | streaming chat |
| GET | `/api/v1/chat/{session_id}/history` | history |
| GET | `/api/v1/chat/sessions` | duplicate session list with search |
| GET | `/api/v1/chat/sessions/{session_id}` | duplicate session detail |
| PUT | `/api/v1/chat/sessions/{session_id}` | duplicate session update |
| DELETE | `/api/v1/chat/sessions/{session_id}` | duplicate session delete |
| POST | `/api/v1/molecules/generate-3d` | 3D generation |
| GET | `/api/v1/molecules/generate-3d/sdf` | quick SDF generation |
| GET | `/api/v1/molecules/card` | molecule card |
| GET | `/api/v1/molecules/search` | public search |
| GET | `/api/v1/molecules/resolve` | name -> CID resolution |
| GET | `/api/v1/molecules/{molecule_id}` | molecule detail |
| GET | `/api/v1/molecules/{molecule_id}/structure/{fmt}` | structure download |
| GET | `/api/v1/molecules/{molecule_id}/structures` | structure versions |
| POST | `/api/v1/molecules/{molecule_id}/calculate` | calculation submit |
| GET | `/api/v1/molecules/calculations/{task_id}` | calculation status |
| POST | `/api/v1/molecules/compare` | compare molecules |
| WS | `/ws/chat/{session_id}` | realtime chat |

## 8. Code Conventions Cheat Sheet

### 8.1 Naming Rules

- Python files: snake_case.
- Python classes: PascalCase.
- React components: PascalCase.
- hooks: camelCase beginning with `use`.
- store files: camelCase ending with `Store`.

### 8.2 File Structure Rules

- backend routes go under `backend/app/routers/`.
- request/response contracts go under `backend/app/schemas/`.
- backend business logic goes under `backend/app/services/`.
- frontend pages go under `frontend/src/app/`.
- reusable frontend UI goes under `frontend/src/components/`.

### 8.3 Prefer Patterns Like This

Backend route + schema:

```python
@router.post("", response_model=SessionResponse)
async def create_session(
    body: SessionCreate,
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    ...
```

Frontend API client wrapper:

```ts
const res = await fetch(url, {
  headers,
  ...options,
});
```

### 8.4 Avoid Patterns Like This

- monolithic page files that parse, fetch, dedupe, and render everything inline,
- direct construction of URLs with broken template escaping,
- using undeclared globals like `log` inside async service helpers,
- depending on development auth bypass as if it were production behavior.

### 8.5 DO

- add new backend business logic under the appropriate `services` subtree,
- keep request/response contracts in `schemas`,
- route external provider integration through wrapper modules,
- preserve existing Pydantic and SQLAlchemy patterns.

### 8.6 DON’T

- add more direct chemistry logic into routers unless it is already local and intentionally scoped,
- add more duplicate session CRUD surfaces,
- put new major logic into `frontend/src/app/chat/page.tsx`,
- assume the compose stack is the runnable truth without checking the current scripts.

## 9. Known Gotchas & Complexity Hotspots

### 9.1 Hotspots

| File | Why It Is Risky |
|---|---|
| `frontend/src/app/chat/page.tsx` | monolithic active UI with real bugs and legacy overlap |
| `backend/app/services/molecule_engine/orchestrator.py` | central coupling point for search/detail/card/calc |
| `backend/app/services/intelligence/agent.py` | tool loop + extraction + enrichment complexity |
| `backend/app/routers/molecules.py` | mixes route handling with chemistry logic and patch drift |
| `frontend/src/components/chat/MoleculePanel.tsx` | direct external fetches, large UI-state surface |

### 9.2 Active Defects to Remember

- `frontend/src/app/chat/page.tsx`: `displayContent` is referenced before declaration.
- `frontend/src/app/chat/page.tsx`: `resolvedTextMols` is computed but `textCidMols` is used in `allMols`.
- `frontend/src/lib/api.ts`: `generate3DSdf` URL contains a literal escaped template expression.
- `frontend/src/app/molecule/[id]/page.tsx`: malformed JSX in the structure-source badge.
- `frontend/src/components/molecule/MoleculeCardFull.tsx`: fallback link uses `data.cid` where route expects internal UUID.
- `backend/app/services/intelligence/agent.py`: `_enrich_molecules_with_smiles` uses undefined `log`.
- `backend/app/services/intelligence/fallback_router.py`: raises `LLMError(model="all", ...)` with a mismatched constructor.
- `backend/app/services/molecule_engine/query_resolver.py`: reads `result.get("text")` from a client that normalizes to `content`.
- `backend/app/services/molecule_engine/orchestrator.py`: references `self._xtb_runner` though constructor stores `self._xtb`.
- `backend/app/routers/molecules.py`: top-level `HTTPException` uses lack module import coverage.

### 9.3 Setup Gotchas

- Dockerfiles missing despite compose declarations.
- no actual tests despite pytest configuration and README claims.
- chemistry runtime dependencies are incomplete in package metadata.
- committed secrets must not be propagated.

## 10. Module Dependency Graph

```text
frontend/src/app/chat/page.tsx
  -> frontend/src/lib/api.ts
  -> frontend/src/components/molecule/MoleculeCardFull.tsx
  -> frontend/src/components/chat/MoleculePanel.tsx

frontend/src/app/molecule/[id]/page.tsx
  -> frontend/src/lib/api.ts
  -> frontend/src/components/molecule/Viewer3D.tsx
  -> frontend/src/components/molecule/PropertyTable.tsx

backend/app/routers/chat.py
  -> backend/app/services/intelligence/agent.py
  -> backend/app/models/session.py
  -> backend/app/schemas/chat.py

backend/app/services/intelligence/agent.py
  -> fallback_router.py
  -> prompt_builder.py
  -> hallucination_guard.py
  -> tools/*

backend/app/routers/molecules.py
  -> backend/app/services/molecule_engine/orchestrator.py
  -> layer1_structure/*
  -> layer2_calculation/task_queue.py

backend/app/services/molecule_engine/orchestrator.py
  -> query_resolver.py
  -> cache_manager.py
  -> layer0_search/aggregator.py
  -> layer1_structure/*
  -> layer2_calculation/*
  -> backend/app/models/*
```

## 11. Environment & Deployment Quick Reference

### 11.1 Main URLs

| Item | URL / Value |
|---|---|
| frontend base path | `/molchat` |
| backend health (compose) | `http://localhost:8000/api/v1/health` |
| backend health (WSL scripts) | `http://localhost:8333/api/v1/health` |
| frontend local | `http://localhost:3000/molchat` |
| WebSocket | `ws://<host>/ws/chat/{session_id}` |

### 11.2 Common Commands

```bash
cd backend && alembic upgrade head
cd backend && uvicorn app.main:app --reload --port 8333
cd frontend && npm install
cd frontend && npm run dev
bash start-molchat.sh
```

### 11.3 Env Summary

- Postgres expected on `5433` host side.
- Redis expected on `6379`.
- Ollama expected on `11434`.
- frontend env files currently set `NEXT_PUBLIC_API_URL=/molchat` and `NEXT_PUBLIC_WS_URL=/molchat`.

## 12. “Where Do I Put This?” Decision Tree

```text
Need a new HTTP endpoint?
  -> backend/app/routers/
  -> add or update corresponding schema in backend/app/schemas/

Need new backend orchestration logic?
  -> backend/app/services/
  -> choose intelligence/ or molecule_engine/ by domain

Need new DB table?
  -> backend/app/models/
  -> add Alembic migration under backend/alembic/versions/

Need a new React page?
  -> frontend/src/app/

Need a reusable UI component?
  -> frontend/src/components/
  -> choose chat/, molecule/, or common/

Need a shared browser API wrapper or runtime helper?
  -> frontend/src/lib/

Need global frontend state?
  -> frontend/src/stores/

Need a custom React hook?
  -> frontend/src/hooks/
```

## 13. Fast Reference Notes for Future AI Agents

- Treat `frontend/src/app/chat/page.tsx` as the active chat implementation, even though the repo also contains Zustand/WebSocket chat pieces.
- Treat `backend/app/services/molecule_engine/orchestrator.py` as the authoritative molecule workflow entrypoint.
- Do not assume Compose is runnable.
- Do not assume tests exist.
- Do not expose committed secrets from env files in patches, docs, or logs.
- If you need to add a cache-backed model, also add a migration; the repo already shows what happens when that step is skipped.

---

## Scan Metadata

| Item | Value |
|---|---|
| Scan date | `2026-03-28 17:16:23 +09:00` |
| Workspace root | `C:\Users\user\Desktop\molcaht\molchat\v3` |
| Total scanned files | `178` |
| Total scanned lines | `60,146` |
| Core documents generated | `5` |
| Elapsed time | not available from the exposed shell/session metadata |
| Notes | file count excludes build artifacts such as `node_modules`, `.next`, `__pycache__`, `dist`, `build`, and `.git` |

## Report Footer

This integrated markdown report was generated from the completed deep-scan findings and intentionally preserves implementation drift, missing assets, and unresolved architectural risks instead of smoothing them over.
