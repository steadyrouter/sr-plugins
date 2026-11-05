from typing import IO

from dify_plugin import OAICompatSpeech2TextModel

from models._common import check_key, set_endpoint


class SteadyRouterSpeech2TextModel(OAICompatSpeech2TextModel):
    def _invoke(self, model: str, credentials: dict, file: IO[bytes], user: str | None = None) -> str:
        set_endpoint(credentials)
        return super()._invoke(model, credentials, file, user)

    def validate_credentials(self, model: str, credentials: dict) -> None:
        check_key(credentials)
