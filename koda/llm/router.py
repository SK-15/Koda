import os
from langchain_anthropic import ChatAnthropic
from tools.registry import all_tools

_llm = None

def get_llm():
      global _llm
      if _llm is None:
          _llm = ChatAnthropic(
              model="claude-sonnet-4-5",
              api_key=os.getenv("ANTHROPIC_KEY_A"),
              max_tokens=4096,
          ).bind_tools(_get_tool_schemas())
      return _llm

def _get_tool_schemas():
      schemas = []
      for tool in all_tools():
          schemas.append({
              "name": tool.name,
              "description": tool.description,
              "input_schema": tool.input_class.model_json_schema(),
          })
      return schemas