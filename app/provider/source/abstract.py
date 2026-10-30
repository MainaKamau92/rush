from abc import ABC, abstractmethod

from app.models.source_access import SourceTool, ToolCall, ToolOutput


class SourceProviderAbstract(ABC):
    name: str

    @abstractmethod
    def ticket_call(self, reference: str) -> ToolCall: ...

    @abstractmethod
    def guideline_call(self, reference: str) -> ToolCall: ...

    @abstractmethod
    async def list_tools(self) -> list[SourceTool]: ...

    @abstractmethod
    async def call_tool(self, call: ToolCall) -> ToolOutput: ...

    @abstractmethod
    async def close(self) -> None: ...
