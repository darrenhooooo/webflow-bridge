"""Side B — browser-use agent (LLM decides everything).

The agent only ever sees `tasks.py`'s one-sentence natural-language goal plus
the start page URL.  No selector, no element id, no expected value, no step
list is ever put into the prompt, and no page helper is injected (red line 3).

LLM: DeepSeek over its OpenAI-compatible endpoint through browser-use's
ChatOpenAI, so the real API usage lands in ChatInvokeUsage.
"""
import asyncio
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Keep browser-use's own state out of the user's home / outside this repo.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("BROWSER_USE_DISABLE_EXTENSIONS", "1")
os.environ.setdefault("BROWSER_USE_CONFIG_DIR", "/tmp/wb-bench-bu-config")
os.environ.setdefault("BROWSER_USE_HEADLESS", "true")
os.environ.setdefault("BROWSER_USE_SETUP_LOGGING", "false")

from common import FIXTURES, TASK_TIMEOUT, truncate, url        # noqa: E402
from tasks import SAMPLE_FILE                                  # noqa: E402

MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
MAX_STEPS = 25

# LiteLLM pricing keys used by browser-use's own TokenCost service; we keep a
# local copy of the same upstream table only as a fallback / cross-check.
PRICE_TABLE = "/tmp/litellm_prices.json"
PRICE_TABLE_URL = ("https://raw.githubusercontent.com/BerriAI/litellm/"
                   "main/model_prices_and_context_window.json")


def find_chromium():
    """The playwright-installed chromium (isolated from the user's Chrome)."""
    pats = [
        os.path.expanduser(
            "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/"
            "Google Chrome for Testing.app/Contents/MacOS/"
            "Google Chrome for Testing"),
        os.path.expanduser(
            "~/.cache/ms-playwright/chromium-*/chrome-mac*/"
            "Google Chrome for Testing.app/Contents/MacOS/"
            "Google Chrome for Testing"),
        os.path.expanduser(
            "~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome"),
    ]
    hits = []
    for pat in pats:
        hits += glob.glob(pat)
    if not hits:
        raise RuntimeError("no playwright chromium found; run "
                           "`python -m playwright install chromium`")
    return sorted(hits)[-1]


def build_llm():
    from browser_use import ChatOpenAI
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set in the environment")
    base_url = os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL
    return ChatOpenAI(
        model=MODEL,
        base_url=base_url,
        api_key=api_key,
        temperature=None,
        frequency_penalty=None,
        max_completion_tokens=8192,
        # DeepSeek has no OpenAI `json_schema` strict mode and rejects a forced
        # tool_choice, so the schema rides the system prompt and the model
        # answers with bare JSON (verified against the endpoint).
        add_schema_to_system_prompt=True,
        dont_force_structured_output=True,
    )


class BuPage:
    """judge.py adapter for side B (browser-use's own CDP session)."""

    def __init__(self, session):
        self.session = session

    async def evaluate(self, expression, tab=None):
        pages = await self.session.get_pages()
        if tab is None:
            target = await self.session.get_current_page()
        else:
            target = next((p for p in pages if p._target_id == tab), None)
        if target is None:
            raise RuntimeError(f"page not found (tab={tab!r})")
        raw = await target.evaluate(f"() => JSON.stringify(({expression}))")
        if raw in ("", None):
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw

    async def tabs(self):
        return [p._target_id for p in await self.session.get_pages()]


def _local_cost(prompt_tokens, cached_tokens, completion_tokens):
    """Cross-check cost from the same upstream LiteLLM table browser-use
    uses.  Fetched once into PRICE_TABLE if it is not already there."""
    try:
        if not os.path.exists(PRICE_TABLE):
            import urllib.request
            with urllib.request.urlopen(PRICE_TABLE_URL, timeout=30) as r:
                data = r.read()
            with open(PRICE_TABLE, "wb") as fh:
                fh.write(data)
        with open(PRICE_TABLE, "r", encoding="utf-8") as fh:
            table = json.load(fh)
        entry = table[MODEL]
        uncached = max(0, (prompt_tokens or 0) - (cached_tokens or 0))
        return (uncached * entry["input_cost_per_token"]
                + (cached_tokens or 0)
                * (entry.get("cache_read_input_token_cost") or 0)
                + (completion_tokens or 0) * entry["output_cost_per_token"])
    except Exception:                                  # noqa: BLE001
        return None


class SideB:
    def __init__(self, art_root):
        self.art_root = art_root
        self.llm = None
        self.session = None

    async def open(self):
        from browser_use import BrowserProfile, BrowserSession
        self.llm = build_llm()
        profile = BrowserProfile(
            executable_path=find_chromium(),
            user_data_dir=tempfile_dir("bu-profile"),
            headless=True,
            keep_alive=True,          # we judge the page AFTER the agent stops
            is_local=True,
            enable_default_extensions=False,
            accept_downloads=True,
            downloads_path=os.path.join(self.art_root, "downloads"),
            viewport={"width": 1280, "height": 900},
        )
        self.session = BrowserSession(browser_profile=profile)
        await self.session.start()
        return self.session.cdp_url

    async def close(self):
        if self.session is not None:
            try:
                await self.session.stop()
            except Exception:                          # noqa: BLE001
                pass
            self.session = None

    async def run_task(self, task, art_dir):
        from browser_use import Agent
        os.makedirs(art_dir, exist_ok=True)
        t0 = time.time()
        first = [None]
        agent = Agent(
            task=f"{task['goal']}\n\nStart from this page: {url(task['page'])}",
            llm=self.llm,
            browser_session=self.session,
            use_vision=False,          # the DeepSeek text models see no images
            use_judge=False,           # no second LLM; we judge externally
            calculate_cost=True,
            enable_signal_handler=False,
            max_actions_per_step=5,
            step_timeout=120,
            llm_timeout=120,
            available_file_paths=([SAMPLE_FILE] if task["id"] == "T5" else None),
            file_system_path=art_dir,
        )

        async def on_step_end(_agent):
            step_count[0] += 1
            if first[0] is None:
                first[0] = time.time() - t0

        error = None
        history = None
        step_count = [0]
        try:
            history = await asyncio.wait_for(
                agent.run(max_steps=MAX_STEPS, on_step_end=on_step_end),
                timeout=TASK_TIMEOUT)
        except asyncio.TimeoutError:
            error = f"task timeout after {TASK_TIMEOUT:.0f}s"
        except Exception as exc:                       # noqa: BLE001
            error = truncate(f"{type(exc).__name__}: {exc}")

        seconds = time.time() - t0
        metrics = {
            "seconds": seconds,
            "time_to_first_action_s": first[0],
            # history.number_of_steps() == len(history.history), i.e. the same
            # count on_step_end increments.  On a timeout there is no history,
            # so the callback counter is the only honest source of the step
            # count — without it a timed-out task would wrongly report 0 steps
            # while still reporting its real token spend.
            "steps_b": (history.number_of_steps() if history
                        else step_count[0]),
            "prompt_tokens_b": 0,
            "completion_tokens_b": 0,
            "cached_tokens_b": 0,
            "est_cost_usd_b": None,
            "cost_source": None,
            "final_result": None,
            "agent_errors": [],
        }
        usage = getattr(history, "usage", None) if history else None
        if usage is None and agent.token_cost_service is not None:
            try:
                usage = await agent.token_cost_service.get_usage_summary()
            except Exception:                          # noqa: BLE001
                usage = None
        if usage is not None:
            metrics["prompt_tokens_b"] = usage.total_prompt_tokens
            metrics["completion_tokens_b"] = usage.total_completion_tokens
            metrics["cached_tokens_b"] = usage.total_prompt_cached_tokens
            if usage.total_cost:
                metrics["est_cost_usd_b"] = usage.total_cost
                metrics["cost_source"] = "browser-use TokenCost (LiteLLM table)"
        if metrics["est_cost_usd_b"] in (None, 0.0):
            local = _local_cost(metrics["prompt_tokens_b"],
                                metrics["cached_tokens_b"],
                                metrics["completion_tokens_b"])
            if local is not None:
                metrics["est_cost_usd_b"] = local
                metrics["cost_source"] = "local LiteLLM table cross-check"
        if history is not None:
            try:
                metrics["final_result"] = truncate(history.final_result(), 300)
            except Exception:                          # noqa: BLE001
                pass
            try:
                metrics["agent_errors"] = [
                    truncate(e, 200) for e in (history.errors() or []) if e]
            except Exception:                          # noqa: BLE001
                metrics["agent_errors"] = []
        return error, metrics


def tempfile_dir(prefix):
    import tempfile
    return tempfile.mkdtemp(prefix=f"wb-bench-{prefix}-")
