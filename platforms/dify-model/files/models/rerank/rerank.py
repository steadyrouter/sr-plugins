from dify_plugin import OAICompatRerankModel
from dify_plugin.entities.model.rerank import RerankResult

from models._common import check_key, set_endpoint


class SteadyRouterRerankModel(OAICompatRerankModel):
    def _invoke(
        self,
        model: str,
        credentials: dict,
        query: str,
        docs: list[str],
        score_threshold: float | None = None,
        top_n: int | None = None,
        user: str | None = None,
    ) -> RerankResult:
        set_endpoint(credentials)
        return super()._invoke(model, credentials, query, docs, score_threshold, top_n, user)

    def validate_credentials(self, model: str, credentials: dict) -> None:
        check_key(credentials)
