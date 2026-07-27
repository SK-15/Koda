import pytest

from tools.structured_output_validator_tool import (
    StructuredOutputValidatorTool,
    StructuredOutputValidatorInput,
)


class TestStructuredOutputValidatorTool:
    def setup_method(self):
        self.tool = StructuredOutputValidatorTool()

    def test_tool_metadata(self):
        assert self.tool.name == "structured_output_validator"
        assert self.tool.risk_level == "low"
        assert self.tool.requires_approval is False

    def test_validate_input_rejects_empty_data(self):
        input = StructuredOutputValidatorInput(data="  ", json_schema={"type": "object"})
        assert self.tool.validate_input(input, "/ws") is False

    def test_validate_input_rejects_empty_schema(self):
        input = StructuredOutputValidatorInput(data="{}", json_schema={})
        assert self.tool.validate_input(input, "/ws") is False

    @pytest.mark.asyncio
    async def test_execute_valid_data(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        result = await self.tool.execute(
            StructuredOutputValidatorInput(data='{"name": "koda"}', json_schema=schema),
            {"workspace_path": "/ws"},
        )
        assert result == "Valid"

    @pytest.mark.asyncio
    async def test_execute_invalid_against_schema(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        result = await self.tool.execute(
            StructuredOutputValidatorInput(data='{"age": 5}', json_schema=schema),
            {"workspace_path": "/ws"},
        )
        assert result.startswith("Invalid :")

    @pytest.mark.asyncio
    async def test_execute_malformed_json(self):
        result = await self.tool.execute(
            StructuredOutputValidatorInput(data="{not json}", json_schema={"type": "object"}),
            {"workspace_path": "/ws"},
        )
        assert result.startswith("Invalid : data is not valid JSON")

    @pytest.mark.asyncio
    async def test_execute_bad_schema(self):
        result = await self.tool.execute(
            StructuredOutputValidatorInput(data="{}", json_schema={"type": "not-a-real-type"}),
            {"workspace_path": "/ws"},
        )
        assert result.startswith("Error : schema itself is invalid")
