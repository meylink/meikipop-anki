# src/dictionary/lookup.py
import logging
import threading
from collections import OrderedDict
from typing import List

from src.config.config import config, MAX_DICT_ENTRIES
from src.dictionary.customdict import DictionaryEntry
from src.dictionary.yomitan_client import YomitanClient

JAPANESE_SEPARATORS = {"、", "。", "「", "」", "｛", "｝", "（", "）", "【", "】", "『", "』", "〈", "〉", "《", "》", "：", "・", "／",
                       "…", "︙", "‥", "︰", "＋", "＝", "－", "÷", "？", "！", "．", "～", "―", "!", "?"}

logger = logging.getLogger(__name__)

class Lookup(threading.Thread):
    def __init__(self, shared_state, popup_window):
        super().__init__(daemon=True, name="Lookup")
        self.shared_state = shared_state
        self.popup_window = popup_window
        self.last_hit_result = None

        self.lookup_cache = OrderedDict()
        self.CACHE_SIZE = 500

        # Initialize Yomitan Client
        self.yomitan_client = None
        if config.is_enabled and config.yomitan_enabled: 
            self.yomitan_client = YomitanClient(config.yomitan_api_url)
            logger.info("Yomitan API mode initialized.")
        else:
            logger.warning("Yomitan API is disabled in config. No lookup will be performed.")

    def run(self):
        logger.debug("Lookup thread started.")
        while self.shared_state.running:
            try:
                hit_result = self.shared_state.lookup_queue.get()
                if not self.shared_state.running: break
                logger.debug("Lookup: Triggered")

                # hit_result is now a dict or None
                # Extract lookup_string for comparison
                current_lookup_string = hit_result["lookup_string"] if hit_result else None
                last_lookup_string = self.last_hit_result["lookup_string"] if self.last_hit_result else None

                # skip lookup if lookup_string didnt change
                if current_lookup_string == last_lookup_string:
                    continue
                
                # Skip lookups for different words when popup is locked
                if self.shared_state.popup_locked_on_result and self.shared_state.popup_locked_lookup_string:
                    if current_lookup_string and current_lookup_string != self.shared_state.popup_locked_lookup_string:
                        logger.debug(f"Lookup: Skipping '{current_lookup_string}' - locked on '{self.shared_state.popup_locked_lookup_string}'")
                        continue
                
                self.last_hit_result = hit_result

                lookup_result = self.lookup(current_lookup_string) if current_lookup_string else None
                self.popup_window.set_latest_data(lookup_result, hit_result)
            except:
                logger.exception("An unexpected error occurred in the lookup loop. Continuing...")
        logger.debug("Lookup thread stopped.")

    def lookup(self, lookup_string):
        if not lookup_string:
            return []
            
        if self.yomitan_client and config.yomitan_enabled:
             return self._lookup_yomitan(lookup_string)
        
        return []

    def _lookup_yomitan(self, lookup_string: str) -> List[DictionaryEntry]:
        logger.info(f"Looking up in Yomitan API: {lookup_string}")
        
        cleaned_lookup_string = lookup_string.strip()
        for i, char in enumerate(cleaned_lookup_string):
            if char in JAPANESE_SEPARATORS:
                cleaned_lookup_string = cleaned_lookup_string[:i]
                break

        truncated_lookup = cleaned_lookup_string[:config.max_lookup_length]
        
        if truncated_lookup in self.lookup_cache:
            self.lookup_cache.move_to_end(truncated_lookup)
            return self.lookup_cache[truncated_lookup]
        
        found_entries = []
        seen_keys = set()
        
        # Scan decreasing length
        for i in range(len(truncated_lookup), 0, -1):
             prefix = truncated_lookup[:i]
             
             entries = self.yomitan_client.lookup(prefix)
             if entries:
                 for entry in entries:
                     # Deduplicate by (written_form, reading) to allow same kanji with different readings
                     # e.g. "数" -> "kazu" and "suu" should both be shown.
                     # "虹" -> "niji" and "niji" should be deduplicated.
                     key = (entry.written_form, entry.reading)
                     if key not in seen_keys:
                         # Assign a unique ID for this session to ensure UI components don't conflict
                         entry.id = len(found_entries) 
                         # IMPORTANT: Set match_len so popup knows how much of the string is the "Word"
                         if not getattr(entry, 'match_len', 0):
                             entry.match_len = len(prefix)
                         seen_keys.add(key)
                         found_entries.append(entry)
                     else:
                        # Find existing entry and merge
                         existing = next((e for e in found_entries if (e.written_form, e.reading) == key), None)
                         if existing:
                             # Merge tags
                             existing.tags.update(entry.tags)
                             existing.frequency_tags.update(entry.frequency_tags)
                             
                             # Merge Senses carefully
                             for new_sense in entry.senses:
                                 new_glosses = new_sense.get('glosses')
                                 is_sense_present = False
                                 for existing_sense in existing.senses:
                                     if existing_sense.get('glosses') == new_glosses:
                                         # Merge POS
                                         existing_pos = existing_sense.get('pos', [])
                                         new_pos = new_sense.get('pos', [])
                                         merged_pos = sorted(list(set(existing_pos + new_pos)))
                                         existing_sense['pos'] = merged_pos
                                         is_sense_present = True
                                         break
                                 
                                 if not is_sense_present:
                                     existing.senses.append(new_sense)
                 
                 # Break early logic from original code?
                 if found_entries and (len(truncated_lookup) - i) > 2: # Stop scanning if we are 2 chars shorter than longest match
                     break
        
        self.lookup_cache[truncated_lookup] = found_entries
        if len(self.lookup_cache) > self.CACHE_SIZE:
             self.lookup_cache.popitem(last=False)
             
        return found_entries
