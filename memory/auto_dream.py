from celery import shared_task
from llm.router import get_llm
from memory.memory_manager import MemoryManager
from langchai_core.messages import HumanMessage
import asyncio

RECONCILE_PROMPT = """You are reviewing memory files for an AI agent session.
  Find any contradictions or outdated facts between these domain files.
  Rewrite each affected file with reconciled, accurate content.
  Return JSON: {{"domain_name": "reconciled content", ...}}
  Only include domains that need changes.

  Domain files:
  {domains}
  """

@shared_task(queue="memory", bind=True)
def run_auto_dream(self, thread_id: str, workspace_path: str):
    asyncio.run(_run_auto_dream(thread_id, workspace_path))


async def _run_auto_dream(thread_id: str, workspace_path: str):
    manager = MemoryManager(thread_id, workspace_path)
    domains = manager.load_all_domains()

    if len(domains) < 2:
        return

    formatted = "\n\n".join(
        f"### {name}\n{content}"
        for name, content in domains.items()
    )

    llm = get_llm()
    response = await llm.ainvoke([
        HumanMessage(content=RECONCILE_PROMPT.format(domains=formatted))
    ])

    import json
    try:
        updates = json.loads(response.content)
        for domain, content in updates.items():
            manager.write_domain(domain, content)
    except json.JSONDecodeError:
        pass

