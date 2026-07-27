import json

import jsonschema
from pydantic import BaseModel

from tools.base import BaseTool, trim_tool_output


class StructuredOutputValidatorInput(BaseModel):
    data: str  # JSON string to validate
    json_schema: dict


class StructuredOutputValidatorTool(BaseTool):
    name = "structured_output_validator"
    description = "Validate a JSON string against a JSON Schema. Returns 'Valid' or the validation error."
    risk_level = "low"
    requires_approval = False

    def validate_input(self, input: StructuredOutputValidatorInput, workspace_path: str = "") -> bool:
        return bool(input.data.strip()) and bool(input.json_schema)

    async def execute(self, input: StructuredOutputValidatorInput, state: dict) -> str:
        if not self.validate_input(input, state.get("workspace_path", "")):
            return "Error : data and json_schema must not be empty"

        try:
            parsed = json.loads(input.data)
        except json.JSONDecodeError as e:
            return f"Invalid : data is not valid JSON - {e}"

        try:
            jsonschema.validate(instance=parsed, schema=input.json_schema)
        except jsonschema.ValidationError as e:
            return trim_tool_output(f"Invalid : {e.message} (path: {list(e.path)})", max_tokens=2000)
        except jsonschema.SchemaError as e:
            return f"Error : schema itself is invalid - {e.message}"

        return "Valid"
