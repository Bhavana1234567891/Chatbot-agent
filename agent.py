"""Connect the prompt and the two tools in one LangChain loop."""

from pathlib import Path
import os
import time

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")


def _configure_tracing() -> None:
    """Turn on LangSmith when .env has an API key."""
    key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY") or ""
    project = os.getenv("LANGCHAIN_PROJECT") or os.getenv("LANGSMITH_PROJECT") or "fashion-ranking-agent"
    endpoint = os.getenv("LANGCHAIN_ENDPOINT") or os.getenv("LANGSMITH_ENDPOINT") or "https://api.smith.langchain.com"

    os.environ["LANGSMITH_PROJECT"] = project
    os.environ["LANGCHAIN_PROJECT"] = project
    os.environ["LANGSMITH_ENDPOINT"] = endpoint
    os.environ["LANGCHAIN_ENDPOINT"] = endpoint
    if key:
        os.environ["LANGSMITH_API_KEY"] = key
        os.environ["LANGCHAIN_API_KEY"] = key
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        return

    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"


_configure_tracing()

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from openai import (
    APIResponseValidationError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from langsmith import traceable

from tools.get_values import get_values as lookup_values
from prompt.prompt_builder import build_system_prompt
from tools.run_sql import run_sql as execute_sql

MAX_STEPS = 15
REQUEST_TIMEOUT = 30
RETRY_LIMIT = 3
CIRCUIT_LIMIT = 3

SYSTEM_PROMPT = build_system_prompt()


def _non_empty(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("must not be empty")
    return text


class GetValuesArgs(BaseModel):
    """Arguments for the get_values tool."""

    model_config = ConfigDict(extra="forbid")
    column: str = Field(min_length=1)
    contains: str = Field(min_length=1)

    @field_validator("column", "contains")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _non_empty(value)


class RunSqlArgs(BaseModel):
    """Arguments for the run_sql tool."""

    model_config = ConfigDict(extra="forbid")
    sql: str = Field(min_length=1)

    @field_validator("sql")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return _non_empty(value)


@tool(args_schema=GetValuesArgs)
def get_values(column: str, contains: str) -> str:
    """Look up the stored spelling of a value before using it in SQL.

    column is the products column you think the text belongs to.
    contains is the text from the question, such as a brand, color, or product name.
    """
    return lookup_values(column, contains)


@tool(args_schema=RunSqlArgs)
def run_sql(sql: str) -> str:
    """Run one read-only SELECT on the products table and return the rows."""
    return execute_sql(sql)


TOOLS = {
    "get_values": get_values,
    "run_sql": run_sql,
}

SCHEMAS = {
    "get_values": GetValuesArgs,
    "run_sql": RunSqlArgs,
}

# max_retries=0 so this file owns the retry, not the HTTP client.
llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    timeout=REQUEST_TIMEOUT,
    max_retries=0,
).bind_tools([get_values, run_sql])


class CircuitBreaker:
    """Stop calling the model after repeated failures."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.failures = 0

    def open(self) -> bool:
        return self.failures >= self.limit

    def record_success(self) -> None:
        self.failures = 0

    def record_failure(self) -> None:
        self.failures += 1


circuit = CircuitBreaker(CIRCUIT_LIMIT)
RETRYABLE = (
    APITimeoutError,
    InternalServerError,
    RateLimitError,
    APIResponseValidationError,
)


def _validate(name: str, arguments) -> tuple[str | None, dict | None]:
    """Check the tool name and parse arguments with Pydantic."""
    if name not in SCHEMAS:
        allowed = ", ".join(SCHEMAS)
        return f"Unknown tool '{name}'. Use only: {allowed}.", None
    try:
        parsed = SCHEMAS[name].model_validate(arguments)
    except ValidationError as exc:
        message = exc.errors()[0]["msg"]
        return f"Invalid arguments for {name}: {message}", None
    return None, parsed.model_dump()


# Past user turns, replies, and tool results. The system prompt is not stored here.
history = []


def last_five_turns(turns):
    """Keep the last 5 user questions and everything that followed them."""
    starts = [i for i, message in enumerate(turns) if isinstance(message, HumanMessage)]
    if len(starts) > 5:
        return turns[starts[-5]:]
    return turns


def _chunk_text(chunk) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return ""


def _stream_once(messages):
    """Yield text as the model writes it. Return the finished message."""
    if circuit.open():
        text = "The model service is paused after repeated failures. Try again later."
        yield text
        return text

    for attempt in range(RETRY_LIMIT):
        try:
            gathered = None
            for chunk in llm.stream(messages):
                gathered = chunk if gathered is None else gathered + chunk
                # Tool-call chunks are not the answer. Only show written text.
                if not getattr(chunk, "tool_call_chunks", None):
                    text = _chunk_text(chunk)
                    if text:
                        yield text
            circuit.record_success()
            calls = []
            if gathered is not None:
                calls = getattr(gathered, "tool_calls", None) or []
            if gathered is None or (not calls and not (gathered.content or "").strip()):
                text = "The model returned an empty answer."
                yield text
                return text
            return gathered
        except RETRYABLE:
            if attempt == RETRY_LIMIT - 1:
                circuit.record_failure()
                text = "The model service failed after retries. Try again in a moment."
                yield text
                return text
            time.sleep(2**attempt)
    text = "The model service failed after retries. Try again in a moment."
    yield text
    return text


@traceable(name="answer", run_type="chain")
def answer_stream(question: str):
    """Yield the answer as it is written. The model may call tools at most 15 times."""
    history.append(HumanMessage(content=question))
    for step in range(MAX_STEPS):
        messages = [SystemMessage(content=SYSTEM_PROMPT), *last_five_turns(history)]
        response = yield from _stream_once(messages)
        if isinstance(response, str):
            history.append(AIMessage(content=response))
            return
        calls = getattr(response, "tool_calls", None) or []
        if not calls:
            history.append(response)
            return
        if step == MAX_STEPS - 1:
            break
        history.append(response)
        for call in calls:
            problem, arguments = _validate(call["name"], call["args"])
            content = problem if problem else TOOLS[call["name"]].invoke(arguments)
            history.append(ToolMessage(content=str(content), tool_call_id=call["id"]))
    stopped = "Stopped after 15 steps. Ask a narrower question about the products table."
    history.append(AIMessage(content=stopped))
    yield stopped


def answer(question: str) -> str:
    """Answer one question. Used by the terminal."""
    return "".join(answer_stream(question))


def main() -> None:
    """Ask from the terminal. One question as an argument, or a prompt loop."""
    import sys

    if len(sys.argv) > 1:
        print(answer(" ".join(sys.argv[1:])))
        return

    print("Ask about the dress rankings. Type quit to stop.")
    while True:
        question = input("\nYou: ").strip()
        if question.lower() in {"quit", "exit"}:
            break
        if question:
            print(answer(question))


if __name__ == "__main__":
    main()
