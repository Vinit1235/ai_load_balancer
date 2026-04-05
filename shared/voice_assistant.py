"""
Voice assistant helpers for asking cluster status by speech or text.

The browser handles speech-to-text and text-to-speech for free.
This module turns the transcript into a concise status answer and
optionally upgrades the wording with Gemini when an API key is present.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from shared.config import settings

logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _summarize_nodes(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    if not nodes:
        return {
            "top_node": None,
            "avg_cpu": 0.0,
            "avg_ram": 0.0,
            "avg_thermal": 0.0,
        }

    avg_cpu = sum(_safe_float(node.get("cpu")) for node in nodes) / len(nodes)
    avg_ram = sum(_safe_float(node.get("ram")) for node in nodes) / len(nodes)
    avg_thermal = sum(_safe_float(node.get("thermal")) for node in nodes) / len(nodes)

    top_node = max(
        nodes,
        key=lambda node: (
            _safe_float(node.get("cpu")),
            _safe_float(node.get("thermal")),
            _safe_float(node.get("ram")),
        ),
    )

    return {
        "top_node": top_node,
        "avg_cpu": round(avg_cpu, 1),
        "avg_ram": round(avg_ram, 1),
        "avg_thermal": round(avg_thermal, 1),
    }


def build_voice_context(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact context object for voice responses."""
    nodes = snapshot.get("nodes", []) or []
    task_status = snapshot.get("task_status", {}) or {}
    node_summary = _summarize_nodes(nodes)

    return {
        "working": snapshot.get("working", 0),
        "nodes_online": snapshot.get("nodes_online", len(nodes)),
        "tasks_total": snapshot.get("tasks_total", 0),
        "task_status": task_status,
        "recent_tasks": snapshot.get("recent_tasks", [])[:10],
        **node_summary,
    }


def _fallback_answer(query: str, context: Dict[str, Any]) -> str:
    query_lower = query.lower().strip()
    nodes_online = context["nodes_online"]
    tasks_total = context["tasks_total"]
    working = context["working"]
    task_status = context["task_status"]
    top_node = context["top_node"]

    if nodes_online == 0:
        return "No worker nodes are online right now. Check the sentinel on each worker and the network link to the master."

    if any(word in query_lower for word in ["slow", "hot", "overload", "drain", "worker"]):
        if top_node:
            node_name = top_node.get("name") or top_node.get("id") or "the busiest node"
            cpu = _safe_float(top_node.get("cpu"))
            ram = _safe_float(top_node.get("ram"))
            thermal = _safe_float(top_node.get("thermal"))
            status = str(top_node.get("status", "HEALTHY"))
            return (
                f"{node_name} looks like the busiest node. It is at {cpu:.1f}% CPU, {ram:.1f}% RAM, "
                f"and {thermal:.1f}°C thermal reading with status {status}."
            )

    completed = task_status.get("completed", 0)
    pending = task_status.get("pending", 0)
    assigned = task_status.get("assigned", 0)
    running = task_status.get("running", 0)

    if any(word in query_lower for word in ["task", "jobs", "queue"]):
        return (
            f"There are {tasks_total} tasks total: {pending} pending, {assigned} assigned, "
            f"{running} running, and {completed} completed. {nodes_online} nodes are online."
        )

    return (
        f"Cluster status is available. {nodes_online} nodes are online, {working} tasks are active, "
        f"and {completed} tasks are completed out of {tasks_total} total."
    )


def _ai_answer(query: str, context: Dict[str, Any]) -> str:
    try:
        import google.generativeai as genai
    except Exception as exc:  # pragma: no cover - import guard
        raise RuntimeError(f"Gemini client unavailable: {exc}") from exc

    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(settings.LLM_MODEL)

    # Token Saver: Only load the Heavy SOP.md if the user complains of errors or asks "how/why" questions
    query_lower = query.lower()
    needs_knowledge = any(keyword in query_lower for keyword in 
       ["how", "explain", "architecture", "what is", "recover", "fail", "error", "sop", "why"]
    )

    project_knowledge_text = ""
    if needs_knowledge:
        import os
        knowledge_path = os.path.join(os.path.dirname(__file__), "..", "SOP.md")
        try:
            if os.path.exists(knowledge_path):
                with open(knowledge_path, "r", encoding="utf-8") as f:
                    # Cut down to 2000 chars to save even more tokens
                    project_knowledge_text = f"\n--- PROJECT KNOWLEDGE ---\n{f.read()[:2000]}\n--------------------------\n"
        except Exception as e:
            logger.warning(f"Failed to load project knowledge: {e}")

    prompt = (
        "You are a highly intelligent voice assistant for the 'NeuroCluster' Distributed AI Load Balancer dashboard. "
        "Keep your reply conversational, spoken-friendly, and avoid returning markdown formatting. "
        "Use the Cluster Snapshot JSON to answer questions about the current state of the system (e.g. CPU loads, queues).\n"
        f"{project_knowledge_text}\n"
        f"User question: {query}\n\n"
        f"Cluster snapshot JSON:\n{json.dumps(context, indent=2, default=str)}"
    )

    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": settings.LLM_TEMPERATURE,
            "max_output_tokens": settings.LLM_MAX_TOKENS,
        },
    )

    text = getattr(response, "text", None)
    if text:
        return text.strip()

    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        parts = getattr(getattr(candidate, "content", None), "parts", None) or []
        joined = " ".join(getattr(part, "text", "") for part in parts).strip()
        if joined:
            return joined

    raise RuntimeError("Gemini returned an empty response")


def build_voice_status_response(query: str, snapshot: Dict[str, Any], use_ai: bool = True) -> Dict[str, Any]:
    """Return a concise answer for voice or text status questions."""
    context = build_voice_context(snapshot)
    provider = "local"

    answer = _fallback_answer(query, context)
    if use_ai and settings.LLM_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
        try:
            answer = _ai_answer(query, context)
            provider = "gemini"
        except Exception as exc:
            logger.warning("Gemini voice answer failed, falling back to local summary: %s", exc)

    return {
        "ok": True,
        "provider": provider,
        "query": query,
        "answer": answer,
        "snapshot": context,
    }
