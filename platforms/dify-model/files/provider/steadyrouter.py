from dify_plugin import ModelProvider
from models._common import check_key


class SteadyRouterProvider(ModelProvider):
    def validate_provider_credentials(self, credentials: dict) -> None:
        check_key(credentials)
