from dify_plugin import OAICompatEmbeddingModel
from dify_plugin.entities.model import EmbeddingInputType
from dify_plugin.entities.model.text_embedding import TextEmbeddingResult

from models._common import check_key, set_endpoint


class SteadyRouterTextEmbeddingModel(OAICompatEmbeddingModel):
    def _invoke(
        self,
        model: str,
        credentials: dict,
        texts: list[str],
        user: str | None = None,
        input_type: EmbeddingInputType = EmbeddingInputType.DOCUMENT,
    ) -> TextEmbeddingResult:
        set_endpoint(credentials)
        return super()._invoke(model, credentials, texts, user, input_type)

    def validate_credentials(self, model: str, credentials: dict) -> None:
        check_key(credentials)

    def get_num_tokens(self, model: str, credentials: dict, texts: list[str]) -> list[int]:
        set_endpoint(credentials)
        return super().get_num_tokens(model, credentials, texts)
