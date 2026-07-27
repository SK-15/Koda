import base64
import mimetypes
from pathlib import Path

from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from tools.base import BaseTool, trim_tool_output


class VisionDescribeInput(BaseModel):
    image: str  # http(s) URL or workspace-relative file path
    prompt: str = "Describe this image in detail."
    model: str | None = None


class VisionDescribeTool(BaseTool):
    name = "vision_describe"
    description = "Send an image (URL or workspace file) to a vision-capable LLM and return a text description."
    risk_level = "low"
    requires_approval = False

    def validate_input(self, input: VisionDescribeInput, workspace_path: str = "") -> bool:
        return bool(input.image.strip())

    def _resolve_image_url(self, image: str, workspace_path: str) -> str | None:
        if image.startswith("http://") or image.startswith("https://"):
            return image

        resolved = Path(workspace_path).joinpath(image).resolve()
        if not str(resolved).startswith(str(Path(workspace_path).resolve())):
            return None
        if not resolved.exists():
            return None

        mime, _ = mimetypes.guess_type(str(resolved))
        mime = mime or "image/png"
        data = base64.b64encode(resolved.read_bytes()).decode()
        return f"data:{mime};base64,{data}"

    async def execute(self, input: VisionDescribeInput, state: dict) -> str:
        workspace_path = state.get("workspace_path", "")
        if not self.validate_input(input, workspace_path):
            return "Error : image must not be empty"

        image_url = self._resolve_image_url(input.image, workspace_path)
        if image_url is None:
            return f"Error : image not found or outside workspace - {input.image}"

        try:
            from llm.router import _build_base_llm
            llm = _build_base_llm(input.model)
            message = HumanMessage(content=[
                {"type": "text", "text": input.prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ])
            response = await llm.ainvoke([message])
        except Exception as e:
            return f"Error : vision request failed - {e}"

        return trim_tool_output(response.content, max_tokens=2000)
