# 🧪 MolChat — AI-Powered Molecular Intelligence Chatbot

[![CI](https://github.com/your-org/molchat/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/molchat/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://python.org)
[![Next.js 14](https://img.shields.io/badge/Next.js-14-black.svg)](https://nextjs.org)

**MolChat**은 자연어 대화를 통해 분자 정보를 검색·시각화·계산할 수 있는
AI 기반 화학 인텔리전스 챗봇입니다.

---

## ✨ 주요 기능

| 기능                 | 설명                                                        |
| -------------------- | ----------------------------------------------------------- |
| 🔍 **분자 검색**     | PubChem · ChEMBL · ChemSpider · ZINC-22 통합 검색           |
| 🧬 **3D 시각화**     | 3Dmol.js 기반 인터랙티브 분자 뷰어                          |
| ⚗️ **양자 계산**     | xTB(GFN2-xTB) 기반 에너지·최적화·진동 계산                  |
| 🤖 **AI 대화**       | Gemini 2.5 Flash + Qwen3 로컬 폴백 LLM                      |
| 🛡️ **환각 방지**     | 3단계 Hallucination Guard (cross-ref, confidence, citation) |
| 📊 **속성 대시보드** | 분자량·LogP·TPSA·회전 결합 등 실시간 속성 패널              |

---

## 🛠️ 기술 스택

| Layer       | Technology                                     |
| ----------- | ---------------------------------------------- |
| Frontend    | Next.js 14, TypeScript, Tailwind CSS, 3Dmol.js |
| Backend     | FastAPI, Python 3.11+, SQLAlchemy 2.0, Celery  |
| AI/ML       | Google Gemini 2.5 Flash, Ollama (Qwen3), RDKit |
| Calculation | xTB (GFN2-xTB), Open Babel                     |
| Database    | PostgreSQL 16, Redis 7.2                       |
| Infra       | Docker Compose, Nginx, GitHub Actions CI/CD    |

---

## 🚀 Quick Start

### 1. 저장소 클론

```bash
git clone https://github.com/your-org/molchat.git
cd molchat
```

### 2. 환경 변수 설정

```bash
cp .env.example .env.prod
# .env.prod 파일을 열어 필수 값 입력 (GEMINI_API_KEY 등)
```

### 3. 서비스 실행

```bash
docker compose --env-file .env.prod up -d
```

### 4. Ollama 모델 다운로드

```bash
./scripts/pull_ollama_models.sh
```

### 5. DB 마이그레이션 & 시드 데이터

```bash
docker compose exec api alembic upgrade head
./scripts/seed_data.sh
```

### 6. 접속

- **Frontend**: http://localhost:3000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/api/v1/health

---

## 🧑‍💻 개발 모드

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## 🧪 테스트

```bash
# Unit tests
pytest tests/unit -v --cov=app --cov-report=term-missing

# Integration tests
pytest tests/integration -v

# E2E tests
pytest tests/e2e -v

# Gold-set benchmark
python tests/benchmarks/gold_set_runner.py
```

---

## 📐 아키텍처

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Next.js UI  │────▶│  FastAPI API  │────▶│  Molecule Engine │
│  (3Dmol.js)  │◀────│  (WebSocket)  │◀────│  L0/L1/L2 Layers│
└─────────────┘     └──────┬───────┘     └────────┬────────┘
                           │                       │
                    ┌──────▼───────┐     ┌────────▼────────┐
                    │ Intelligence  │     │   PostgreSQL 16  │
                    │ Gemini+Qwen3  │     │   Redis 7.2      │
                    └──────────────┘     └─────────────────┘
```

---

## 📚 문서

- [설계 문서 (Design Doc)](docs/DESIGN_DOC.html)
- [기여 가이드 (Contributing)](docs/CONTRIBUTING.md)

---

## 📄 License

[MIT](LICENSE) © 2026 MolChat Contributors
