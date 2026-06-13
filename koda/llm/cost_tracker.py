import os
from sqlalchemy import select, update
from infra.postgres import get_session_factory, ThreadRecord


COST_PER_1K_INPUT_TOKENS = 0.003   # claude-sonnet-4-5 pricing
COST_PER_1K_OUTPUT_TOKENS = 0.015


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    input_cost = (input_tokens / 1000) * COST_PER_1K_INPUT_TOKENS
    output_cost = (output_tokens / 1000) * COST_PER_1K_OUTPUT_TOKENS
    return round(input_cost + output_cost, 6)


async def record_usage(
    thread_id: str,
    org_id: str,
    user_id: str,
    input_tokens: int,
    output_tokens: int,
    last_message: str = "",
):
    cost = estimate_cost(input_tokens, output_tokens)
    total_tokens = input_tokens + output_tokens

    async with get_session_factory()() as session:
        result = await session.execute(
            select(ThreadRecord).where(ThreadRecord.thread_id == thread_id)
        )
        record = result.scalar_one_or_none()

        if record is None:
            session.add(ThreadRecord(
                thread_id=thread_id,
                org_id=org_id,
                user_id=user_id,
                last_message=last_message[:500],
                cost_usd=cost,
                tokens_used=total_tokens,
            ))
        else:
            record.cost_usd += cost
            record.tokens_used += total_tokens
            record.last_message = last_message[:500]

        await session.commit()

    return cost