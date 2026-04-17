import requests
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class AnkiClient:
    def __init__(self, api_url: str):
        self.api_url = api_url.rstrip('/')

    def _invoke(self, action: str, timeout: float = 2.0, **params) -> Any:
        payload = {
            "action": action,
            "version": 6,
            "params": params
        }
        try:
            # Short timeout for UI responsiveness checking
            response = requests.post(self.api_url, json=payload, timeout=timeout)
            response.raise_for_status()
            result = response.json()
            if len(result) != 2:
                raise ValueError("Response has an unexpected number of fields.")
            if "error" not in result:
                raise ValueError("Response is missing required error field.")
            if "result" not in result:
                raise ValueError("Response is missing required result field.")
            if result["error"]:
                raise Exception(result["error"])
            return result["result"]
        except Exception as e:
            logger.error(f"AnkiConnect error ({action}): {e}")
            raise e

    def ping(self) -> bool:
        """Checks if AnkiConnect is reachable and returns True if so."""
        try:
            self._invoke("version")
            return True
        except:
            return False

    def get_deck_names(self) -> List[str]:
        """Returns a list of all deck names."""
        try:
            return self._invoke("deckNames")
        except:
            return []

    def get_model_names(self) -> List[str]:
        """Returns a list of all note type (model) names."""
        try:
            return self._invoke("modelNames")
        except:
            return []

    def get_model_field_names(self, model_name: str) -> List[str]:
        """Returns a list of field names for the given model."""
        try:
            return self._invoke("modelFieldNames", modelName=model_name)
        except:
            return []

    def add_note(self, note_data: Dict[str, Any]) -> int:
        """
        Adds a note to Anki.
        note_data structure should match 'note' param in 'addNote' action.
        Returns the ID of the created note.
        """
        return self._invoke("addNote", note=note_data)

    def store_media_file(self, filename: str, data_base64: str) -> str:
        """Stores a media file in Anki."""
        # Media uploads can take longer than regular metadata actions.
        return self._invoke("storeMediaFile", timeout=15.0, filename=filename, data=data_base64)

    def find_notes(self, query: str) -> List[int]:
        """Finds notes matching the query."""
        try:
            return self._invoke("findNotes", query=query)
        except:
            return []

