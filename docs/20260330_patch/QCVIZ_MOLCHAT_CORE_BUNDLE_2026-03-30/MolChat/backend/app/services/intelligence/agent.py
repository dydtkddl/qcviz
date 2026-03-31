"""
MolChatAgent – top-level conversational agent.

Responsibilities:
  1. Receive user messages and conversation history.
  2. Build prompts with system instructions + tool definitions.
  3. Route to the best available LLM (Gemini → Ollama fallback).
  4. Parse tool-call requests from the LLM response.
  5. Execute tool calls against the Molecule Engine.
  6. Feed tool results back into the LLM for final synthesis.
  7. Run the Hallucination Guard on the final answer.
  8. Return a structured ``AgentResponse``.

Design:
  • Stateless per-request; conversation history is passed in.
  • Supports both synchronous (request/response) and streaming modes.
  • Max tool-call loop depth is capped to prevent infinite recursion.
  • Every step is instrumented with structured logging.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import structlog

from app.core.config import settings
from app.services.intelligence.fallback_router import FallbackRouter, LLMResponse
from app.services.intelligence.hallucination_guard import (
    HallucinationGuard,
    GuardResult,
)
from app.services.intelligence.prompt_builder import PromptBuilder
from app.services.intelligence.tools import get_tool_registry, ToolRegistry

logger = structlog.get_logger(__name__)

_MAX_TOOL_ROUNDS = 5  # Maximum tool-call → LLM loops


@dataclass
class ToolCallResult:
    """Result of executing a single tool call."""

    tool_name: str
    tool_call_id: str
    arguments: dict[str, Any]
    result: dict[str, Any] | str = ""
    success: bool = True
    elapsed_ms: float = 0.0
    error: str = ""


@dataclass
class AgentResponse:
    """Full response from the MolChatAgent."""

    session_id: uuid.UUID | None = None
    content: str = ""
    model_used: str = ""
    token_count: int = 0
    tool_calls: list[ToolCallResult] = field(default_factory=list)
    molecules_referenced: list[dict[str, Any]] = field(default_factory=list)
    confidence: float | None = None
    hallucination_flags: list[str] = field(default_factory=list)
    guard_result: GuardResult | None = None
    elapsed_ms: float = 0.0
    fallback_used: bool = False


@dataclass
class ConversationMessage:
    """A single message in the conversation history."""

    role: str  # system, user, assistant, tool
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    name: str | None = None


class MolChatAgent:
    """Conversational AI agent for molecular chemistry."""

    def __init__(
        self,
        router: FallbackRouter | None = None,
        prompt_builder: PromptBuilder | None = None,
        guard: HallucinationGuard | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._router = router or FallbackRouter()
        self._prompt = prompt_builder or PromptBuilder()
        self._guard = guard or HallucinationGuard()
        self._tools = tool_registry or get_tool_registry()

    # ═══════════════════════════════════════════
    # Synchronous (request/response) mode
    # ═══════════════════════════════════════════

    async def chat(
        self,
        user_message: str,
        *,
        history: list[ConversationMessage] | None = None,
        session_id: uuid.UUID | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentResponse:
        """Process a user message and return a complete response.

        This is the primary entry point for non-streaming interactions.
        """
        t0 = time.perf_counter()
        log = logger.bind(
            session_id=str(session_id) if session_id else None,
            message_preview=user_message[:80],
        )
        log.info("agent_chat_started")

        response = AgentResponse(session_id=session_id)
        history = history or []

        try:
            # ── 1. Build messages ──
            messages = self._build_messages(user_message, history, context)

            # ── 2. Tool-call loop ──
            for round_idx in range(_MAX_TOOL_ROUNDS):
                log.debug("agent_round", round=round_idx + 1)

                # Call LLM
                llm_response = await self._router.generate(
                    messages=messages,
                    tools=self._tools.get_tool_definitions(),
                )

                response.model_used = llm_response.model
                response.token_count += llm_response.token_count
                response.fallback_used = llm_response.fallback_used

                # Check for tool calls
                if llm_response.tool_calls:
                    tool_results = await self._execute_tool_calls(
                        llm_response.tool_calls
                    )
                    response.tool_calls.extend(tool_results)

                    # Collect referenced molecules
                    for tr in tool_results:
                        if isinstance(tr.result, dict):
                            mol_refs = self._extract_molecule_refs(tr.result)
                            response.molecules_referenced.extend(mol_refs)

                    # Append assistant message with tool calls
                    messages.append(ConversationMessage(
                        role="assistant",
                        content=llm_response.content or "",
                        tool_calls=llm_response.tool_calls,
                    ))

                    # Append tool results
                    for tr in tool_results:
                        messages.append(ConversationMessage(
                            role="tool",
                            content=self._serialize_tool_result(tr),
                            tool_call_id=tr.tool_call_id,
                            name=tr.tool_name,
                        ))

                    continue  # Next round

                # No tool calls → final answer
                response.content = llm_response.content or ""
                break

            # ── 2.5 Extract molecules from response text ──
            if response.content and not response.molecules_referenced:
                text_molecules = self._extract_molecules_from_text(response.content)
                if text_molecules:
                    response.molecules_referenced = text_molecules
                    log.info("molecules_extracted_from_text", count=len(text_molecules))

            # ── 2.6 Enrich molecule refs with SMILES from PubChem ──
            if response.molecules_referenced:
                try:
                    await self._enrich_molecules_with_smiles(response.molecules_referenced)
                except Exception as enrich_err:
                    log.debug("smiles_enrichment_failed", error=str(enrich_err))

            # ── 3. Hallucination Guard ──
            if response.content:
                guard_result = await self._guard.check(
                    response=response.content,
                    tool_results=[
                        tr.result for tr in response.tool_calls if tr.success
                    ],
                    context=context,
                )
                response.guard_result = guard_result
                response.confidence = guard_result.confidence
                response.hallucination_flags = guard_result.flags

                # If guard modifies the response
                if guard_result.corrected_response:
                    log.info(
                        "hallucination_guard_corrected",
                        flags=guard_result.flags,
                    )
                    response.content = guard_result.corrected_response

        except Exception as exc:
            log.error("agent_chat_error", error=str(exc))
            response.content = (
                "죄송합니다. 요청을 처리하는 중 오류가 발생했습니다. "
                "잠시 후 다시 시도해 주세요."
            )

        response.elapsed_ms = (time.perf_counter() - t0) * 1000
        log.info(
            "agent_chat_completed",
            model=response.model_used,
            tools_used=len(response.tool_calls),
            elapsed_ms=response.elapsed_ms,
            confidence=response.confidence,
        )
        return response

    # ═══════════════════════════════════════════
    # Streaming mode
    # ═══════════════════════════════════════════

    async def chat_stream(
        self,
        user_message: str,
        *,
        history: list[ConversationMessage] | None = None,
        session_id: uuid.UUID | None = None,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream response tokens as SSE-compatible dicts.

        Yields dicts with keys:
          - ``type``: 'token', 'tool_start', 'tool_result', 'done', 'error'
          - ``data``: the payload
        """
        t0 = time.perf_counter()
        history = history or []
        messages = self._build_messages(user_message, history, context)

        try:
            # First pass: check if LLM wants to call tools
            llm_response = await self._router.generate(
                messages=messages,
                tools=self._tools.get_tool_definitions(),
            )

            if llm_response.tool_calls:
                # Execute tools first, then stream final answer
                for tc in llm_response.tool_calls:
                    yield {
                        "type": "tool_start",
                        "data": {
                            "tool_name": tc.get("name", ""),
                            "arguments": tc.get("arguments", {}),
                        },
                    }

                tool_results = await self._execute_tool_calls(
                    llm_response.tool_calls
                )

                for tr in tool_results:
                    yield {
                        "type": "tool_result",
                        "data": {
                            "tool_name": tr.tool_name,
                            "success": tr.success,
                            "result_preview": str(tr.result)[:200],
                        },
                    }

                # Append tool context and stream final response
                messages.append(ConversationMessage(
                    role="assistant",
                    content=llm_response.content or "",
                    tool_calls=llm_response.tool_calls,
                ))
                for tr in tool_results:
                    messages.append(ConversationMessage(
                        role="tool",
                        content=self._serialize_tool_result(tr),
                        tool_call_id=tr.tool_call_id,
                        name=tr.tool_name,
                    ))

                async for token in self._router.stream(
                    messages=messages, tools=None
                ):
                    yield {"type": "token", "data": token}

            else:
                # No tool calls → stream directly
                async for token in self._router.stream(
                    messages=messages, tools=None
                ):
                    yield {"type": "token", "data": token}

        except Exception as exc:
            logger.error("agent_stream_error", error=str(exc))
            yield {
                "type": "error",
                "data": "스트리밍 중 오류가 발생했습니다.",
            }

        elapsed = (time.perf_counter() - t0) * 1000
        yield {
            "type": "done",
            "data": {"elapsed_ms": elapsed},
        }

    # ═══════════════════════════════════════════
    # Internal helpers
    # ═══════════════════════════════════════════

    def _build_messages(
        self,
        user_message: str,
        history: list[ConversationMessage],
        context: dict[str, Any] | None,
    ) -> list[ConversationMessage]:
        """Assemble the full message list for the LLM."""
        messages: list[ConversationMessage] = []

        # System prompt
        system_prompt = self._prompt.build_system_prompt(context=context)
        messages.append(ConversationMessage(role="system", content=system_prompt))

        # History (truncated to last 20 turns)
        recent_history = history[-40:]  # 20 turns × 2 messages
        messages.extend(recent_history)

        # Current user message
        messages.append(ConversationMessage(role="user", content=user_message))

        return messages

    async def _execute_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> list[ToolCallResult]:
        """Execute a batch of tool calls from the LLM."""
        results: list[ToolCallResult] = []

        for tc in tool_calls:
            tool_name = tc.get("name", tc.get("function", {}).get("name", ""))
            tool_call_id = tc.get("id", str(uuid.uuid4()))
            arguments = tc.get("arguments", tc.get("function", {}).get("arguments", {}))

            if isinstance(arguments, str):
                import json

                try:
                    arguments = json.loads(arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {"raw": arguments}

            t0 = time.perf_counter()
            result = ToolCallResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                arguments=arguments,
            )

            try:
                tool_fn = self._tools.get_tool(tool_name)
                if tool_fn is None:
                    result.success = False
                    result.error = f"Unknown tool: {tool_name}"
                    result.result = {"error": result.error}
                else:
                    output = await tool_fn(**arguments)
                    result.result = output
                    result.success = True

            except Exception as exc:
                logger.warning(
                    "tool_execution_error",
                    tool=tool_name,
                    error=str(exc),
                )
                result.success = False
                result.error = str(exc)
                result.result = {"error": str(exc)}

            result.elapsed_ms = (time.perf_counter() - t0) * 1000

            logger.info(
                "tool_executed",
                tool=tool_name,
                success=result.success,
                elapsed_ms=result.elapsed_ms,
            )
            results.append(result)

        return results

    @staticmethod
    def _serialize_tool_result(tr: ToolCallResult) -> str:
        """Serialize a tool result for injection into the LLM context."""
        import json

        if isinstance(tr.result, str):
            return tr.result
        try:
            return json.dumps(tr.result, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(tr.result)


    @staticmethod
    def _extract_molecules_from_text(text: str) -> list:
        """Extract molecule names from LLM response text."""
        import re

        NOT_MOL = {
            "hbd", "hba", "tpsa", "adme", "ic50", "ec50", "ld50",
            "logp", "pka", "mw", "bbb", "cns", "ppi", "moa", "sar",
            "qsar", "smiles", "inchi", "cas", "fda", "ema", "who",
            "dna", "rna", "atp", "adp", "nad", "nadh", "fad", "coa",
            "nsaid", "nsaids", "otc", "api", "usp",
            "amylase", "protease", "lipase", "enzyme", "protein",
            "receptor", "substrate", "inhibitor", "agonist", "antagonist",
            "starch", "dextrin", "fructose", "sucrose",
            "coffee", "green tea", "black tea", "cocoa", "cola",
            "cyclooxygenase", "prostaglandin", "cox", "cox-1", "cox-2",
            "ligand", "pharmacokinetics", "bioavailability", "lipinski",
            "analgesic", "antipyretic", "anti-inflammatory", "antithrombotic",
            "excretion", "absorption", "distribution", "metabolism",
            "topological", "polar", "surface", "area",
        }

        NOT_MOL_KR = {
            "에너지", "증후군", "소포제", "음료", "드링크", "식품", "건강",
            "치료", "질환", "효과", "부작용", "복용", "처방", "약물",
            "성분", "종류", "기능", "작용", "특징", "방법", "용도",
            "초콜릿", "커피", "녹차", "홍차", "콜라", "사이다", "코코아",
            "에너지 드링크", "초콜릿 음료", "차나무", "커피콩",
            "맥아당", "전해질", "녹말", "덱스트린", "전분",
            "중추신경", "신경전달", "수용체", "효소", "단백질",
            "탄산음료", "소염진통제", "해열진통제", "진통제", "제산제",
            "비타민", "아미노산", "지방산", "탄수화물",
            "배설", "흡수", "분포", "대사", "배출", "축적", "전달",
            "합성", "저해", "사이클로옥시게나제", "프로스타글란딘",
            "혈소판", "위궤양", "중추신경계", "응집", "억제", "활성화",
            "리간드", "경구", "투여", "해열", "진통", "소염", "항혈전",
            "방향족", "지용성", "소화제", "항생제", "항혈전제",
        }

        if not text or len(text) < 10:
            return []

        molecules = []
        seen = set()

        def add(fam: str, pro: str = ""):
            fam = fam.strip().strip("*").strip()
            pro = pro.strip().strip("*").strip() if pro else ""
            if not fam or len(fam) < 2 or len(fam) > 60:
                return
            fl = fam.lower()
            pl = pro.lower() if pro else fl
            if fl in NOT_MOL or pl in NOT_MOL:
                return
            if fam in NOT_MOL_KR or fl in NOT_MOL_KR:
                return
            if fl in seen or pl in seen:
                return
            seen.add(fl)
            if pl != fl:
                seen.add(pl)
            molecules.append({
                "name": pro if pro else fam,
                "familiar_name": fam,
                "professional_name": pro if pro else fam,
            })

        # Pattern 1: **Korean(English)** — split on LAST open-paren to handle names with commas
        for m in re.finditer(r"\*\*([^*]{2,20})\s*[\(（]([^)）]{2,50})[\)）]\*\*", text):
            n1 = m.group(1).strip()
            n2_raw = m.group(2).strip()
            # For English names like "Ursodeoxycholic acid, UDCA" keep full name
            # Only split on comma if the part before comma is >3 chars
            if "," in n2_raw:
                parts = n2_raw.split(",")
                n2 = parts[0].strip()
                # If first part is too short (like "1" from "1,3,7-..."), use full string
                if len(n2) < 3:
                    n2 = n2_raw.strip()
            else:
                n2 = n2_raw
            kr1 = bool(re.search(r"[가-힣]", n1))
            kr2 = bool(re.search(r"[가-힣]", n2))
            if kr1 and not kr2:
                add(n1, n2)
            elif kr2 and not kr1:
                add(n2, n1)
            else:
                add(n1, n2)

        # Pattern 2: Korean (English) without bold
        for m in re.finditer(r"([가-힣]{2,10})\s*[\(（]\s*([A-Za-z][A-Za-z\s\-]{2,40}?)\s*[\)）]", text):
            n2_raw = m.group(2).strip()
            if "," in n2_raw:
                parts = n2_raw.split(",")
                n2 = parts[0].strip() if len(parts[0].strip()) >= 3 else n2_raw
            else:
                n2 = n2_raw
            add(m.group(1), n2)

        # Pattern 3: **BoldEnglish** with chemical suffix
        chem_rx = r"\*\*([A-Z][a-z]+(?:ine|ide|ate|one|cin|lin|rol|fen|xin|pin|nil|zol|mab|nib|vir|rin|min|tan|lol|pam|mide|done|zole|pine|tine|dine|sine|cine|ride)e?)\*\*"
        for m in re.finditer(chem_rx, text):
            add(m.group(1))

        # Pattern 4: **Bold Korean 2-6 chars** if followed by chemical context
        for m in re.finditer(r"\*\*([가-힣]{2,6})\*\*", text):
            name = m.group(1)
            if name in NOT_MOL_KR:
                continue
            # Check context: followed by 은/는/이/의 or (
            after = text[m.end():m.end()+10]
            if re.search(r"^[\s]*[\(（은는이의]", after):
                add(name)

        # Pattern 5: Chemical formulas C8H10N4O2
        for m in re.finditer(r"\b(C\d{1,3}H\d{1,3}(?:[A-Z][a-z]?\d{0,3}){1,5})\b", text):
            if len(m.group(1)) >= 6:
                add(m.group(1))

        # ── Enrich with SMILES from PubChem (best-effort) ──
        import aiohttp

        async def _enrich_smiles(mol_list: list) -> list:
            """Best-effort SMILES enrichment from PubChem."""
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as client:
                    for mol in mol_list:
                        if mol.get("canonical_smiles"):
                            continue
                        search_name = mol.get("professional_name") or mol.get("name", "")
                        if not search_name:
                            continue
                        try:
                            # Get CID
                            cid_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{search_name}/cids/JSON"
                            resp = await client.get(cid_url)
                            if resp.status_code != 200:
                                continue
                            cid = resp.json().get("IdentifierList", {}).get("CID", [None])[0]
                            if not cid:
                                continue
                            mol["cid"] = cid

                            # Get SMILES
                            prop_url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/CanonicalSMILES/JSON"
                            prop_resp = await client.get(prop_url)
                            if prop_resp.status_code == 200:
                                props = prop_resp.json().get("PropertyTable", {}).get("Properties", [{}])[0]
                                smiles = props.get("CanonicalSMILES")
                                if smiles:
                                    mol["canonical_smiles"] = smiles
                        except Exception:
                            continue
            except ImportError:
                # httpx not available — try urllib
                pass
            return mol_list

        # Run enrichment synchronously in this context
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're already in async context — schedule as task
                import concurrent.futures
                # Can't await in staticmethod easily, skip enrichment here
                # Enrichment will happen in the caller (process_message)
                pass
        except Exception:
            pass

        return molecules[:10]
    @staticmethod
    def _extract_molecule_refs(data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract molecule references from tool results."""
        refs: list[dict[str, Any]] = []

        if "molecule" in data:
            refs.append(data["molecule"])
        if "results" in data and isinstance(data["results"], list):
            for item in data["results"]:
                if isinstance(item, dict) and "canonical_smiles" in item:
                    refs.append(item)

        return refs
    async def _enrich_molecules_with_smiles(self, molecules: list[dict]) -> None:
        """PubChem에서 SMILES와 CID를 가져와 molecules_referenced를 보강."""
        import httpx

        if not molecules:
            return

        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            for mol in molecules:
                # 이미 SMILES가 있으면 스킵
                if mol.get("canonical_smiles"):
                    continue

                # professional_name 우선, 없으면 name
                name = mol.get("professional_name") or mol.get("name") or ""
                if not name or len(name) < 2:
                    continue
                name = name.strip()

                try:
                    # Step 1: name → CID
                    url1 = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{name}/cids/JSON"
                    r1 = await client.get(url1)
                    if r1.status_code != 200:
                        continue
                    cids = r1.json().get("IdentifierList", {}).get("CID", [])
                    if not cids:
                        continue
                    cid = cids[0]

                    # Step 2: CID → CanonicalSMILES
                    url2 = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/property/CanonicalSMILES/JSON"
                    r2 = await client.get(url2)
                    if r2.status_code == 200:
                        props = r2.json().get("PropertyTable", {}).get("Properties", [{}])[0]
                        smiles = props.get("CanonicalSMILES", "")
                        if smiles:
                            mol["canonical_smiles"] = smiles
                            mol["cid"] = cid
                            log.info("smiles_enriched", name=name, cid=cid, smiles=smiles)
                        else:
                            mol["cid"] = cid
                    else:
                        mol["cid"] = cid

                except Exception as e:
                    log.warning("smiles_enrichment_error", name=name, error=str(e))
                    continue
