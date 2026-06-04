import asyncio
from uuid import uuid4
from langchain_core.messages import HumanMessage
from coordinator.worker_spawner import WorkerAgent, WORKER_DEFAULT_TOOLS
from llm.router import get_llm


DECOMPOSE_PROMPT = """Break this task into independent subtasks that can run in parallel.
Each subtask must be self-contained — no subtask should depend on another's output.
Return one subtask per line. Max 5 subtasks. No numbering, no bullets.

Task: {task}
"""

AGGREGATE_PROMPT = """Combine these worker results into a single coherent response.
Be concise. Resolve any contradictions. Present unified findings.

Results:
{results}
"""


class Coordinator:
    def __init__(
        self,
        workspace_path: str,
        org_id: str = "default",
        user_id: str = "default",
        max_workers: int = 5,
        elevated: bool = False,
    ):
        self.workspace_path = workspace_path
        self.org_id = org_id
        self.user_id = user_id
        self.max_workers = max_workers
        self.elevated = elevated

    async def run(self, task: str) -> str:
        subtasks = await self._decompose(task)
        subtasks = subtasks[:self.max_workers]

        workers = [
            WorkerAgent(
                task=subtask,
                workspace_path=self.workspace_path,
                thread_id=f"worker:{self.org_id}:{uuid4()}",
                allowed_tools=WORKER_DEFAULT_TOOLS,
                org_id=self.org_id,
                user_id=self.user_id,
            )
            for subtask in subtasks
        ]

        results = await asyncio.gather(*[w.run() for w in workers])

        return await self._aggregate(task, results)

    async def _decompose(self, task: str) -> list[str]:
        llm = get_llm()
        response = await llm.ainvoke([
            HumanMessage(content=DECOMPOSE_PROMPT.format(task=task))
        ])
        lines = [l.strip() for l in response.content.splitlines() if l.strip()]
        return lines

    async def _aggregate(self, task: str, results: list[str]) -> str:
        formatted = "\n\n---\n\n".join(
            f"Worker {i+1}:\n{r}" for i, r in enumerate(results)
        )
        llm = get_llm()
        response = await llm.ainvoke([
            HumanMessage(content=AGGREGATE_PROMPT.format(results=formatted))
        ])
        return response.content