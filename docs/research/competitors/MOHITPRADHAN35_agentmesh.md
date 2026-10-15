# 🕸️ AgentMesh: Multi-Agent Persistent Memory on FalkorDB

[![Hackathon Track](https://img.shields.io/badge/Track-Agent%20Memory%20%26%20Coordination-6366f1.svg?style=for-the-badge)](#-hackathon-tracks-entered)
[![Secondary Track](https://img.shields.io/badge/Track-Company%20Brain-ec4899.svg?style=for-the-badge)](#-hackathon-tracks-entered)
[![Graph Database](https://img.shields.io/badge/Database-FalkorDB%20(Latest)-dc2626.svg?style=for-the-badge)](https://github.com/FalkorDB/FalkorDB)
[![Repository](https://img.shields.io/badge/GitHub-MOHITPRADHAN35%2Fagentmesh-181717.svg?style=for-the-badge&logo=github)](https://github.com/MOHITPRADHAN35/agentmesh)
[![Backend](https://img.shields.io/badge/Backend-FastAPI%20%7C%20Python%203.11+-009688.svg?style=for-the-badge)](https://fastapi.tiangolo.com)
[![Frontend](https://img.shields.io/badge/Frontend-React%2019%20%7C%20XYFlow%20%7C%20Tailwind-3b82f6.svg?style=for-the-badge)](https://react.dev)

> **AgentMesh** is an active persistent-memory and relationship engine for autonomous multi-agent teams. Built natively on **FalkorDB**, AgentMesh transforms ephemeral chat sessions into a living, interconnected knowledge graph. It enables cross-session memory recall, multi-agent state coordination, automatic contradiction detection, and evidence-backed answers with strict graph provenance.

---

## 🏆 Hackathon Tracks Entered

1. **Primary Track: Agent Memory and Coordination**  
   *Enables specialized agents (Researcher, Planner, Reviewer) to share a unified graph state, preserve decisions across isolated sessions, and track how knowledge evolves over time.*
2. **Secondary Track: Company Brain**  
   *Maintains institutional knowledge, traces the historical lineage of architectural choices, and surfaces organizational contradictions before they turn into costly mistakes.*

---

## 📋 Hackathon Submission Deliverables (Rule #10 Compliance)

| Submission Requirement | Implementation / Status | Reference Link |
| :--- | :--- | :--- |
| **1. Public Source-Code Repository** | Open-source repository with full Git history | [github.com/MOHITPRADHAN35/agentmesh](https://github.com/MOHITPRADHAN35/agentmesh) |
| **2. Setup Instructions & Graph Data Model** | Complete instructions + full ASCII schema diagram and node/edge tables | [Jump to Graph Data Model](#-graph-data-model) |
| **3. Cypher Queries & Algorithms** | Multi-hop traversal, contradiction linking, and idempotent ingestion | [Jump to Cypher Queries](#-core-cypher-queries-used-by-agents) |
| **4. Demo Video** | Video walkthrough showing cross-session continuity & contradiction detection | *(Insert your YouTube/Loom/Drive link here)* |
| **5. Live Deployment / Local Setup** | Docker Compose (`docker compose up -d`) & local dev commands verified | [Jump to Setup Instructions](#-quickstart--local-setup) |
| **6. Track Specified** | **Agent Memory and Coordination** (Primary) & **Company Brain** (Secondary) | [Jump to Tracks](#-hackathon-tracks-entered) |

---

## 💡 The Core Problem & FalkorDB Solution

### The Problem
* **Session Amnesia:** Agents lose context the moment a session closes.
* **Factual & Architectural Drift:** As teams converse across multiple days, agents accept conflicting statements (e.g. *"We use Postgres"* on Monday vs *"We use MongoDB"* on Wednesday) without realizing they contradict earlier decisions.
* **Black-Box Reasoning:** Standard LLMs hallucinate answers without verifiable evidence trails or provenance.

### The Shift: FalkorDB as the Context Engine
Instead of treating memory as passive vector text, **FalkorDB acts as an active relational engine**. When an agent learns something new:
1. It traverses historical graph paths across earlier sessions.
2. It detects clashes and links them with `[:CONTRADICTS]`.
3. It preserves both facts with full provenance rather than silently overwriting historical decisions.
4. It connects actionable work with `[:INFORMS]->(:Task)`.

> **FalkorDB is load-bearing:** If you remove FalkorDB, cross-session continuity, contradiction resolution, and task lineage completely collapse. The graph is the engine, not decoration.

---

## 📐 Graph Data Model

```
       (Agent) ──[:CREATED]──> (Memory) ──[:INFORMS]──> (Task)
                                  │   ▲
                     [:CONTAINS]  │   │ [:RELATES_TO | SUPPORTS | CONTRADICTS]
                                  ▼   │
      (Session) ──────────────> (Memory)
                                  ▲
                                  │ [:INVOLVES]
                                  │
                              (Conflict)
```

### Node Schema
| Node Label | Key Properties | Description |
| :--- | :--- | :--- |
| **`Session`** | `id`, `title`, `created_at` | Represents a distinct conversation or workspace session. |
| **`Agent`** | `name`, `role` | Specialized agent identity (`Researcher`, `Planner`, `Reviewer`). |
| **`Memory`** | `id`, `text`, `type`, `confidence`, `source`, `session_id`, `created_at` | Atomic knowledge statement, decision, or constraint. |
| **`Conflict`** | `id`, `reason`, `status` (`open` \| `resolved`), `created_at`, `resolution` | Tracks contradictory assertions between memories. |
| **`Task`** | `id`, `title`, `status`, `priority` | Actionable work items derived from confirmed memories. |

### Edge Schema
* `(:Session)-[:CONTAINS]->(:Memory)`: Chronological containment across user sessions.
* `(:Agent)-[:CREATED]->(:Memory)`: Agent provenance of who extracted or verified the memory.
* `(:Memory)-[:RELATES_TO]->(:Memory)`: Semantic and topic adjacency.
* `(:Memory)-[:SUPPORTS]->(:Memory)`: Validating or reinforcing evidence.
* `(:Memory)-[:CONTRADICTS]->(:Memory)`: Direct clash between incompatible facts/decisions.
* `(:Conflict)-[:INVOLVES]->(:Memory)`: Connects contradiction records to both opposing memories.
* `(:Memory)-[:INFORMS]->(:Task)`: Lineage connecting decisions to executable tasks.

---

## 🤖 Multi-Agent Triad Workflow

```
                        [ User Input ]
                               │
                               ▼
                    [ 1. Researcher Agent ]
             • Extracts facts, decisions, and constraints.
             • Merges new Memory nodes into FalkorDB.
                               │
                               ▼
                    [ 2. Reviewer Agent ]
             • Queries historical memories in FalkorDB.
             • Identifies contradictions (e.g. Postgres vs Mongo).
             • Creates Conflict node & links [:CONTRADICTS] without destroying history.
                               │
                               ▼
                    [ 3. Planner Agent ]
             • Recalls multi-hop graph context across sessions.
             • Derives and links actionable Tasks: Memory -[:INFORMS]-> Task.
                               │
                               ▼
                   [ Grounded Response ]
             • Synthesizes answer citing exact Memory IDs and graph paths.
```

---

## 🔍 Core Cypher Queries Used by Agents

### 1. Ingestion & Provenance Linking (Researcher)
```cypher
MERGE (s:Session {id: $session_id})
MERGE (m:Memory {id: $id})
ON CREATE SET 
  m.text = $text,
  m.type = $type,
  m.confidence = $confidence,
  m.source = $source,
  m.created_at = $created_at,
  m.agent = $agent,
  m.session_id = $session_id
MERGE (s)-[:CONTAINS]->(m)
WITH m
MATCH (a:Agent {name: $agent})
MERGE (a)-[:CREATED]->(m)
```

### 2. Multi-Hop Memory Retrieval across Sessions (Planner)
```cypher
MATCH (m:Memory)
WHERE toLower(m.text) CONTAINS toLower($query) OR m.id IN $seed_ids
OPTIONAL MATCH (m)-[r:RELATES_TO|SUPPORTS]-(related:Memory)
OPTIONAL MATCH (s:Session)-[:CONTAINS]->(m)
RETURN 
  m.id AS id, 
  m.text AS text, 
  m.type AS type,
  collect(DISTINCT related.text) AS related_facts,
  collect(DISTINCT s.id) AS historical_sessions
LIMIT 20
```

### 3. Contradiction Detection & Linking (Reviewer)
```cypher
MATCH (ma:Memory {id: $mem_a_id}), (mb:Memory {id: $mem_b_id})
MERGE (ma)-[:CONTRADICTS]->(mb)
MERGE (mb)-[:CONTRADICTS]->(ma)
CREATE (c:Conflict {
  id: $conflict_id,
  reason: $reason,
  status: 'open',
  created_at: datetime()
})
MERGE (c)-[:INVOLVES]->(ma)
MERGE (c)-[:INVOLVES]->(mb)
RETURN c.id AS conflict_id
```

### 4. Non-Destructive Conflict Resolution
```cypher
MATCH (c:Conflict {id: $conflict_id})
SET c.status = 'resolved', c.resolution = $resolution, c.note = $note
RETURN c.id, c.status
```

---

## 🖥️ UI Features: VS Code-Style 4-Way Resizable Layout

The frontend includes a developer-centric workspace with **interactive drag-and-drop splitters**:
* **Horizontal Splitters:** Resize the Left Sidebar (Sessions) and Right Panel (Conflicts & Memories) to fit any screen width.
* **Vertical Splitter:** Drag the horizontal handle between the Chat Workspace and the Knowledge Graph explorer.
* **Dynamic Graph Canvas:** Built with `@xyflow/react`, the graph canvas auto-flexes to 100% of any resized panel height.
* **Live Contradiction Panel:** Resolve conflicts interactively (`Accept A`, `Accept B`, `Keep Both`) with one click.

---

## 🚀 Quickstart & Local Setup

### System Prerequisites
* **Docker & Docker Compose** (Docker Desktop on Windows/macOS/Linux)
* **Python 3.11+**
* **Node.js 20+**

---

### Option 1: Docker Compose (All Services)

```bash
# 1. Clone the repository
git clone https://github.com/your-username/agentmesh.git
cd agentmesh

# 2. Launch FalkorDB, Backend, and Frontend
docker compose up -d --build
```

Access points:
* 🌐 **Frontend UI:** [http://localhost:8081](http://localhost:8081)
* ⚙️ **Backend API:** [http://localhost:8000](http://localhost:8000)
* 📖 **Swagger OpenAPI Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
* 🗄️ **FalkorDB Instance:** `localhost:6379`

---

### Option 2: Local Development Setup

#### Step 1: Start FalkorDB
```bash
docker run -p 6379:6379 -it --name agentmesh-falkordb --rm falkordb/falkordb:latest
```

#### Step 2: Start Backend (FastAPI)
```bash
cd backend
python -m venv venv

# Windows:
.\venv\Scripts\activate
# Linux / macOS:
source venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

#### Step 3: Start Frontend (React 19 + TanStack)
```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
# The app opens on http://localhost:8081 (or 8080/5173)
```

---

## 🧪 Testing & Verification

### 1. Run Unit & Schema Tests
```bash
cd backend
python -m pytest -v
```
All tests validate Pydantic contract serialization, contradiction logic, and task planning.

### 2. Run Explicit Demo Seed Script
Populate multi-session scenarios with visible contradiction nodes:
```bash
cd backend
python scripts/seed_demo.py
```

### 3. Query FalkorDB Directly via Redis CLI
```bash
docker exec agentmesh-falkordb redis-cli GRAPH.QUERY agentmesh "MATCH (n) RETURN labels(n)[0] AS Label, count(n) AS Count"
```

---

## 📡 API Reference Summary

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Live database ping and status (`status: "ok"`, `database: true`). |
| `POST` | `/api/sessions` | Create or register a persistent session. |
| `GET` | `/api/sessions` | List all sessions recorded for project. |
| `GET` | `/api/sessions/{id}/messages` | Retrieve conversation history with agent execution traces. |
| `POST` | `/api/chat` | Run Researcher ➔ Reviewer ➔ Planner agent loop. |
| `GET` | `/api/memories` | Search and filter memories by keyword or session. |
| `GET` | `/api/graph` | Serialize nodes and edges for `@xyflow/react` GraphExplorer. |
| `GET` | `/api/conflicts` | List open and resolved contradiction pairs (`a` vs `b`). |
| `POST` | `/api/conflicts/{id}/resolve` | Resolve a contradiction non-destructively. |
| `GET` | `/docs` | Interactive Swagger documentation. |

---

## 📂 Project Structure

```
hackathon/
├── docker-compose.yml                   # FalkorDB + Backend + Frontend compose
├── README.md                            # Comprehensive project guide & Cypher docs
├── overview.md                          # Hackathon challenge overview
├── rules.md                             # Hackathon constraints & deliverables
├── backend/
│   ├── Dockerfile                       # Python 3.11 container
│   ├── requirements.txt                 # FastAPI, FalkorDB, Pydantic, Pytest
│   ├── .env.example & .env              # Environment configurations
│   ├── app/
│   │   ├── main.py                      # FastAPI entrypoint & CORS
│   │   ├── config.py                    # Settings configuration
│   │   ├── models/schemas.py            # Pydantic models for API contracts
│   │   ├── services/
│   │   │   ├── graph_service.py         # Official FalkorDB client & Cypher engine
│   │   │   ├── agent_orchestrator.py    # Researcher -> Reviewer -> Planner cycle
│   │   │   └── llm_provider.py          # Deterministic engine + provider abstraction
│   │   ├── agents/
│   │   │   ├── researcher.py            # Candidate extraction
│   │   │   ├── reviewer.py              # Contradiction detection
│   │   │   └── planner.py               # Context retrieval & task planning
│   │   └── api/
│   │       ├── health.py, sessions.py, chat.py
│   │       ├── memories.py, graph.py, conflicts.py
│   │   └── scripts/seed_demo.py         # Demo data seed script
│   └── tests/
│       ├── test_conflicts.py            # Contradiction evaluation tests
│       └── test_graph.py                # Graph serialization tests
└── frontend/
    ├── Dockerfile                       # Node 22 container
    ├── package.json                     # React 19, @xyflow/react, Tailwind v4
    ├── vite.config.ts                   # TanStack Start / Vite config
    └── src/
        ├── routes/index.tsx             # 4-way VS Code resizable dashboard
        ├── components/
        │   ├── chat/Workspace.tsx       # Multi-agent chat interface
        │   ├── graph/GraphExplorer.tsx  # @xyflow/react Knowledge Graph
        │   ├── conflicts/ConflictPanel.tsx # Contradiction resolution cards
        │   └── ui/resizable.tsx         # VS Code splitters
        └── services/api.ts              # API client connecting to backend
```

---

## ⚖️ Hackathon Compliance Disclosure
* **Required Technology:** FalkorDB is the primary, load-bearing database.
* **AI Tool Disclosure:** Antigravity AI assistant was used for scaffolding, refactoring, and test authoring. All architecture, Cypher design, and graph data modeling have been thoroughly verified and tested.
