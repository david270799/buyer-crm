"""Recognise a photo already uploaded to our storage (the Mini App's
"Распознать" button in the order form).

Gemini only suggests: the fields go back to the form, and nothing is saved
until the admin saves the order. The same validation as for orders from the
group applies (services/recognition.validate): unsure answers come back
empty, a link is never taken from the photo.
"""

from crm.domain.errors import ConfigurationError, NotFoundError, ValidationError
from crm.services.common import Actor, require_admin
from crm.services.recognition import Recognition, RecognitionError, Recognizer
from crm.storage.blobs import BlobStorage


class PhotoRecognitionService:
    def __init__(self, storage: BlobStorage | None, recognizer: Recognizer | None):
        self._storage = storage
        self._recognizer = recognizer

    @property
    def enabled(self) -> bool:
        return self._storage is not None and self._recognizer is not None

    def recognize(self, actor: Actor, photo_url: str, text: str | None = None) -> Recognition:
        require_admin(actor)
        if self._recognizer is None:
            raise ConfigurationError(
                "Распознавание не подключено: на сервере не задан ключ GEMINI_API_KEY."
            )
        if self._storage is None:
            raise ConfigurationError("Хранилище фото не настроено.")
        if not photo_url:
            raise ValidationError("Сначала загрузите фото.")
        image = self._storage.read_url(photo_url)
        if image is None:
            raise NotFoundError("Фото не найдено — загрузите его заново.")
        try:
            return self._recognizer.recognize(image, text)
        except RecognitionError as exc:
            raise ConfigurationError(f"Gemini не ответил: {exc}") from None
