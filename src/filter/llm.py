"""
LLM-based extraction for Lancet.
Uses local Ollama models for fact/claim extraction and summarization.

Per §4.2: LLM processes are destroyed after task completion to prevent memory leaks.
"""

import json
from typing import Any

import aiohttp

from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.utils.lifecycle import (
    get_lifecycle_manager,
    ResourceType,
    register_ollama_session_for_task,
)

logger = get_logger(__name__)


class OllamaClient:
    """Client for Ollama API with lifecycle management.
    
    Per §4.2, LLM processes should be released after task completion.
    This client supports:
    - Task-scoped session management
    - Model unloading to free VRAM
    - Automatic cleanup via lifecycle manager
    """
    
    def __init__(self):
        self._settings = get_settings()
        self._session: aiohttp.ClientSession | None = None
        self._current_model: str | None = None
        self._current_task_id: str | None = None
        self._lifecycle_manager = get_lifecycle_manager()
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120)
            )
        return self._session
    
    def set_task_id(self, task_id: str | None) -> None:
        """Set current task ID for lifecycle tracking.
        
        Args:
            task_id: Task identifier.
        """
        self._current_task_id = task_id
    
    async def close(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def unload_model(self, model: str | None = None) -> bool:
        """Unload model to free VRAM.
        
        Per §4.2: LLM process context should be released after task completion.
        
        Args:
            model: Model name to unload (uses current model if not specified).
            
        Returns:
            True if unload was successful.
        """
        model = model or self._current_model
        if not model:
            return False
        
        try:
            session = await self._get_session()
            url = f"{self._settings.llm.ollama_host}/api/generate"
            
            # Ollama API: POST with keep_alive=0 unloads the model
            payload = {
                "model": model,
                "prompt": "",
                "keep_alive": 0,  # Unload immediately
            }
            
            async with session.post(url, json=payload, timeout=10) as response:
                if response.status == 200:
                    logger.info("Ollama model unloaded", model=model)
                    self._current_model = None
                    return True
                else:
                    logger.debug(
                        "Ollama model unload returned non-200",
                        model=model,
                        status=response.status,
                    )
                    return False
                    
        except Exception as e:
            logger.debug(
                "Ollama model unload failed (may be expected)",
                model=model,
                error=str(e),
            )
            return False
    
    async def cleanup_for_task(self, unload_model: bool = True) -> None:
        """Cleanup resources after task completion.
        
        Args:
            unload_model: Whether to unload the model to free VRAM.
        """
        if unload_model and self._settings.llm.unload_on_task_complete:
            await self.unload_model()
        
        self._current_task_id = None
    
    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate completion from Ollama.
        
        Args:
            prompt: User prompt.
            model: Model name (uses fast_model if not specified).
            system: System prompt.
            temperature: Generation temperature.
            max_tokens: Maximum tokens to generate.
            
        Returns:
            Generated text.
        """
        session = await self._get_session()
        
        if model is None:
            model = self._settings.llm.fast_model
        if temperature is None:
            temperature = self._settings.llm.temperature
        
        # Track current model for cleanup
        self._current_model = model
        
        url = f"{self._settings.llm.ollama_host}/api/generate"
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        
        if system:
            payload["system"] = system
        
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        
        try:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error("Ollama error", status=response.status, error=error_text)
                    raise RuntimeError(f"Ollama error: {response.status}")
                
                data = await response.json()
                return data.get("response", "")
                
        except Exception as e:
            logger.error("Ollama request failed", error=str(e))
            raise
    
    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
    ) -> str:
        """Chat completion from Ollama.
        
        Args:
            messages: List of message dicts with 'role' and 'content'.
            model: Model name.
            temperature: Generation temperature.
            
        Returns:
            Assistant response.
        """
        session = await self._get_session()
        
        if model is None:
            model = self._settings.llm.fast_model
        if temperature is None:
            temperature = self._settings.llm.temperature
        
        url = f"{self._settings.llm.ollama_host}/api/chat"
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        
        try:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error("Ollama chat error", status=response.status, error=error_text)
                    raise RuntimeError(f"Ollama error: {response.status}")
                
                data = await response.json()
                return data.get("message", {}).get("content", "")
                
        except Exception as e:
            logger.error("Ollama chat request failed", error=str(e))
            raise


# Global client
_client: OllamaClient | None = None


def _get_client() -> OllamaClient:
    """Get or create Ollama client."""
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client


async def _cleanup_client() -> None:
    """Close and cleanup the global Ollama client.
    
    Used for testing cleanup and graceful shutdown.
    """
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def cleanup_llm_for_task(task_id: str | None = None) -> None:
    """Cleanup LLM resources after task completion.
    
    Per §4.2: LLM processes should be released after task completion.
    This unloads the model to free VRAM.
    
    Args:
        task_id: Task identifier (for logging).
    """
    global _client
    if _client is not None:
        logger.info("Cleaning up LLM resources for task", task_id=task_id)
        await _client.cleanup_for_task(unload_model=True)


def set_llm_task_id(task_id: str | None) -> None:
    """Set current task ID for LLM lifecycle tracking.
    
    Args:
        task_id: Task identifier.
    """
    global _client
    if _client is not None:
        _client.set_task_id(task_id)


# Prompt templates
EXTRACT_FACTS_PROMPT = """あなたは情報抽出の専門家です。以下のテキストから客観的な事実を抽出してください。

テキスト:
{text}

抽出した事実をJSON配列形式で出力してください。各事実は以下の形式で:
{{"fact": "事実の内容", "confidence": 0.0-1.0の信頼度}}

事実のみを出力し、意見や推測は含めないでください。"""

EXTRACT_CLAIMS_PROMPT = """あなたは情報分析の専門家です。以下のテキストから主張を抽出してください。

リサーチクエスチョン: {context}

テキスト:
{text}

抽出した主張をJSON配列形式で出力してください。各主張は以下の形式で:
{{"claim": "主張の内容", "type": "fact|opinion|prediction", "confidence": 0.0-1.0}}

"""

SUMMARIZE_PROMPT = """以下のテキストを要約してください。重要なポイントを簡潔にまとめてください。

テキスト:
{text}

要約:"""

TRANSLATE_PROMPT = """以下のテキストを{target_lang}に翻訳してください。

テキスト:
{text}

翻訳:"""


async def llm_extract(
    passages: list[dict[str, Any]],
    task: str,
    context: str | None = None,
    use_slow_model: bool = False,
) -> dict[str, Any]:
    """Extract information using LLM.
    
    Args:
        passages: List of passage dicts with 'id' and 'text'.
        task: Task type (extract_facts, extract_claims, summarize, translate).
        context: Additional context (e.g., research question).
        use_slow_model: Whether to use the larger model.
        
    Returns:
        Extraction result.
    """
    client = _get_client()
    settings = get_settings()
    
    model = settings.llm.slow_model if use_slow_model else settings.llm.fast_model
    
    results = []
    
    for passage in passages:
        passage_id = passage.get("id", "unknown")
        text = passage.get("text", "")
        source_url = passage.get("source_url", "")
        
        # Select prompt based on task
        if task == "extract_facts":
            prompt = EXTRACT_FACTS_PROMPT.format(text=text[:4000])
        elif task == "extract_claims":
            prompt = EXTRACT_CLAIMS_PROMPT.format(
                text=text[:4000],
                context=context or "一般的な調査",
            )
        elif task == "summarize":
            prompt = SUMMARIZE_PROMPT.format(text=text[:4000])
        elif task == "translate":
            target_lang = context or "英語"
            prompt = TRANSLATE_PROMPT.format(
                text=text[:4000],
                target_lang=target_lang,
            )
        else:
            raise ValueError(f"Unknown task: {task}")
        
        try:
            response = await client.generate(prompt, model=model)
            
            # Parse response based on task
            if task in ("extract_facts", "extract_claims"):
                # Try to parse JSON
                try:
                    # Find JSON array in response
                    import re
                    json_match = re.search(r"\[.*\]", response, re.DOTALL)
                    if json_match:
                        extracted = json.loads(json_match.group())
                    else:
                        extracted = []
                except json.JSONDecodeError:
                    extracted = [{"raw_response": response}]
                
                results.append({
                    "id": passage_id,
                    "source_url": source_url,
                    "extracted": extracted,
                })
            else:
                results.append({
                    "id": passage_id,
                    "source_url": source_url,
                    "result": response.strip(),
                })
                
        except Exception as e:
            logger.error(
                "LLM extraction error",
                passage_id=passage_id,
                task=task,
                error=str(e),
            )
            results.append({
                "id": passage_id,
                "error": str(e),
            })
    
    # Aggregate results
    if task == "extract_facts":
        all_facts = []
        for r in results:
            for fact in r.get("extracted", []):
                if isinstance(fact, dict):
                    fact["source_passage_id"] = r["id"]
                    fact["source_url"] = r.get("source_url", "")
                    all_facts.append(fact)
        
        return {
            "ok": True,
            "task": task,
            "facts": all_facts,
            "passage_results": results,
        }
    
    elif task == "extract_claims":
        all_claims = []
        for r in results:
            for claim in r.get("extracted", []):
                if isinstance(claim, dict):
                    claim["source_passage_id"] = r["id"]
                    claim["source_url"] = r.get("source_url", "")
                    all_claims.append(claim)
        
        return {
            "ok": True,
            "task": task,
            "claims": all_claims,
            "passage_results": results,
        }
    
    else:
        return {
            "ok": True,
            "task": task,
            "results": results,
        }


async def should_promote_to_slow_model(
    passage: dict[str, Any],
    scores: dict[str, float],
) -> bool:
    """Determine if passage should be processed with slow model.
    
    Args:
        passage: Passage dict.
        scores: Ranking scores (bm25, embed, rerank).
        
    Returns:
        True if slow model should be used.
    """
    settings = get_settings()
    threshold = settings.llm.promote_to_slow_threshold
    
    # Use slow model if rerank score is below threshold
    # (indicates ambiguous/difficult content)
    rerank_score = scores.get("score_rerank", 1.0)
    
    # Normalize rerank score to 0-1 range (assuming sigmoid output)
    normalized = 1 / (1 + pow(2.718, -rerank_score))
    
    # Promote if score is in ambiguous range
    if 0.3 < normalized < threshold:
        return True
    
    return False

