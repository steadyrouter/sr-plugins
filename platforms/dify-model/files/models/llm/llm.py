from collections.abc import Generator

from dify_plugin import OAICompatLargeLanguageModel
from dify_plugin.entities.model import ModelFeature
from dify_plugin.entities.model.llm import LLMMode, LLMResult
from dify_plugin.entities.model.message import PromptMessage, PromptMessageTool

from models._common import check_key, set_endpoint


class SteadyRouterLargeLanguageModel(OAICompatLargeLanguageModel):
    def _prepare(self, model: str, credentials: dict) -> None:
        set_endpoint(credentials)
        credentials["mode"] = LLMMode.CHAT.value
        schema = self.get_model_schema(model, credentials)
        if schema and ModelFeature.TOOL_CALL in (schema.features or []):
            credentials["function_calling_type"] = "tool_call"
            credentials["stream_function_calling"] = "supported"

    def _invoke(
        self,
        model: str,
        credentials: dict,
        prompt_messages: list[PromptMessage],
        model_parameters: dict,
        tools: list[PromptMessageTool] | None = None,
        stop: list[str] | None = None,
        stream: bool = True,
        user: str | None = None,
    ) -> LLMResult | Generator:
        self._prepare(model, credentials)
        return super()._invoke(model, credentials, prompt_messages, model_parameters, tools, stop, stream, user)

    def validate_credentials(self, model: str, credentials: dict) -> None:
        check_key(credentials)

    def get_num_tokens(
        self,
        model: str,
        credentials: dict,
        prompt_messages: list[PromptMessage],
        tools: list[PromptMessageTool] | None = None,
    ) -> int:
        self._prepare(model, credentials)
        return super().get_num_tokens(model, credentials, prompt_messages, tools)
