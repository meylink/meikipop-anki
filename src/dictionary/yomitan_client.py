
import requests
import logging
import html
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from .customdict import DictionaryEntry
from . import structured_content

logger = logging.getLogger(__name__)

class YomitanClient:
    def __init__(self, api_url: str):
        self.api_url = api_url.rstrip('/')
        self.enabled = False
        # Simple check if API is reachable (optional, or rely on config)
        
    def check_connection(self) -> bool:
        try:
            r = requests.post(f"{self.api_url}/yomitanVersion", timeout=1)
            return r.status_code == 200
        except:
            return False

    def lookup(self, term: str) -> List[DictionaryEntry]:
        """
        Fetch definitions from Yomitan API.
        Returns a list of DictionaryEntry objects.
        """
        entries = []
        try:
            response = requests.post(
                f"{self.api_url}/termEntries", 
                json={"term": term}, 
                timeout=2
            )
            
            if response.status_code != 200:
                logger.error(f"Yomitan API returned status {response.status_code}: {response.text}")
                return []
                
            data = response.json()
            # Response: { "dictionaryEntries": [ ... ], "originalTextLength": ... }
            original_text_length = data.get('originalTextLength', 0)
            
            raw_entries = data.get('dictionaryEntries', [])
            
            for idx, raw_entry in enumerate(raw_entries):
                entry = self._convert_api_entry(raw_entry, term, idx)
                if entry:
                    if original_text_length > 0:
                        entry.match_len = original_text_length
                    entries.append(entry)
                    
        except Exception as e:
            logger.error(f"Error querying Yomitan API: {e}")
            return []
            
        # Deduplicate entries
        # Deduplicate entries by HEADWORD (written + reading)
        # Merge contents of duplicates into the first occurrence
        unique_map = {} # (written, reading) -> entry
        
        for entry in entries:
            key = (entry.written_form, entry.reading)
            
            if key in unique_map:
                seen = unique_map[key]
                
                # Merge Tags & Frequencies
                seen.tags.update(entry.tags)
                seen.frequency_tags.update(entry.frequency_tags)
                
                # Merge Deconjugation (prefer existing if present, else take new)
                if not seen.deconjugation_process and entry.deconjugation_process:
                    seen.deconjugation_process = entry.deconjugation_process
                    
                # Merge Senses (Deduplicate based on glosses)
                for new_sense in entry.senses:
                    new_glosses = new_sense.get('glosses')
                    
                    is_sense_present = False
                    for existing_sense in seen.senses:
                        if existing_sense.get('glosses') == new_glosses:
                            # Match found! Merge metadata
                            existing_current_pos = existing_sense.get('pos', [])
                            new_sense_pos = new_sense.get('pos', [])
                            merged_pos = sorted(list(set(existing_current_pos + new_sense_pos)))
                             
                            existing_sense['pos'] = merged_pos
                            # Optional: Merge source? "SourceA, SourceB"? 
                            # For now, keep original source or maybe just ignore diffs to keep clean.
                            is_sense_present = True
                            break
                    
                    if not is_sense_present:
                        seen.senses.append(new_sense)
                        
            else:
                unique_map[key] = entry
                
        return list(unique_map.values())

    def anki_fields(self, text: str, markers: List[str], max_entries: int = 10, include_media: bool = False, entry_type: str = "term") -> Dict[str, Any]:
        """Render Yomitan Anki fields and optional media payload for the given text."""
        response = requests.post(
            f"{self.api_url}/ankiFields",
            json={
                "text": text,
                "type": entry_type,
                "markers": markers,
                "maxEntries": max_entries,
                "includeMedia": include_media,
            },
            timeout=3,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return {}
        return data

    def get_audio_media(self, term: str, reading: str = "") -> Optional[Dict[str, str]]:
        """
        Returns a dict with matching Yomitan audio media for the provided term/reading:
        {
            "filename": "...mp3",
            "content": "<base64>",
            "mediaType": "audio/mpeg"
        }
        """
        term = (term or "").strip()
        reading = (reading or "").strip()
        if not term and not reading:
            return None

        query_text = term or reading
        try:
            data = self.anki_fields(
                text=query_text,
                markers=["expression", "reading", "audio"],
                max_entries=10,
                include_media=True,
                entry_type="term",
            )
        except Exception as e:
            logger.debug(f"Yomitan ankiFields audio request failed: {e}")
            return None

        fields = data.get("fields", []) if isinstance(data, dict) else []
        audio_media = data.get("audioMedia", []) if isinstance(data, dict) else []
        if not isinstance(fields, list) or not isinstance(audio_media, list) or not audio_media:
            return None

        target_filename = ""
        if fields:
            scored = []
            for f in fields:
                if not isinstance(f, dict):
                    continue

                audio_marker = str(f.get("audio", ""))
                match = re.search(r"\[sound:([^\]]+)\]", audio_marker)
                if not match:
                    continue

                fname = match.group(1).strip()
                f_term = str(f.get("expression", "")).strip()
                f_read = str(f.get("reading", "")).strip()

                score = 0
                if term and f_term == term:
                    score += 3
                if reading and f_read == reading:
                    score += 2
                if term and f_read == term:
                    score += 1

                scored.append((score, fname))

            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                target_filename = scored[0][1]

        target_item = None
        if target_filename:
            target_item = next((m for m in audio_media if isinstance(m, dict) and m.get("ankiFilename") == target_filename), None)

        if target_item is None:
            target_item = next((m for m in audio_media if isinstance(m, dict)), None)
            if target_item and not target_filename:
                target_filename = str(target_item.get("ankiFilename", ""))

        if not target_item:
            return None

        content = str(target_item.get("content", ""))
        media_type = str(target_item.get("mediaType", ""))
        filename = target_filename or str(target_item.get("ankiFilename", ""))

        if not filename or not content:
            return None

        return {
            "filename": filename,
            "content": content,
            "mediaType": media_type,
        }

    def get_term_marker_value(self, term: str, reading: str, marker: str) -> str:
        """Return a rendered Anki marker value for the best matching term/reading entry."""
        term = (term or "").strip()
        reading = (reading or "").strip()
        marker = (marker or "").strip()
        if not marker or (not term and not reading):
            return ""

        query_text = term or reading
        try:
            data = self.anki_fields(
                text=query_text,
                markers=["expression", "reading", marker],
                max_entries=10,
                include_media=False,
                entry_type="term",
            )
        except Exception as e:
            logger.debug(f"Yomitan ankiFields marker request failed ({marker}): {e}")
            return ""

        fields = data.get("fields", []) if isinstance(data, dict) else []
        if not isinstance(fields, list) or not fields:
            return ""

        best_value = ""
        best_score = -1
        for f in fields:
            if not isinstance(f, dict):
                continue
            value = str(f.get(marker, ""))
            if not value:
                continue

            f_term = str(f.get("expression", "")).strip()
            f_read = str(f.get("reading", "")).strip()

            score = 0
            if term and f_term == term:
                score += 3
            if reading and f_read == reading:
                score += 2
            if term and f_read == term:
                score += 1

            if score > best_score:
                best_score = score
                best_value = value

        return best_value

    def _convert_api_entry(self, item: Dict[str, Any], lookup_term: str, index: int) -> Optional[DictionaryEntry]:
        """
        Converts a single API dictionary entry object to DictionaryEntry.
        """
        # API entry structure:
        # {
        #   "headwords": [ { "term": "...", "reading": "...", ... } ],
        #   "definitions": [ { "content": ..., "dictionary": "..." } ],
        #   ...
        # }
        
        headwords = item.get('headwords', [])
        if not headwords:
            return None
            
        # Use first headword for main term/reading
        # Ideally we might split into multiple entries if multiple headwords?
        # But 'headwords' usually grouped by same sense.
        primary_headword = headwords[0]
        written_form = primary_headword.get('term', lookup_term)
        reading = primary_headword.get('reading', '')

        # Collect tags/frequencies from wrapper if available, or headword
        tags = set()
        # API structure for tags might be in 'tags' list of strings or objects
        # Looking at docs/examples: headwords have tags, definitions have tags.
        # Let's aggregate tags from headwords?
        for h in headwords:
            for t in h.get('tags', []):
                if isinstance(t, dict): 
                    tags.add(t.get('name', '')) # 'name' or 'content'? Example says 'content' for detailed tag object?
                    # wait, example: "tags": [ { "name": "priority...", "content": ["..."] } ]
                    # simple tags might serve just fine if present.
                    # Or 'wordClasses' -> "v5"
                elif isinstance(t, str):
                    tags.add(t)
            for wc in h.get('wordClasses', []):
                 tags.add(wc)

        frequency_tags = set()
        frequencies = item.get('frequencies', [])
        for f in frequencies:
            # f: { dictionary: "...", frequency: 123, ... }
            d_name = f.get('dictionaryAlias') or f.get('dictionary', '')
            val = f.get('displayValue') or f.get('frequency')
            if d_name and val:
                # Store each frequency as its own entry (not grouped)
                frequency_tags.add(f"{d_name}: {val}")

        # Senses
        senses = []
        definitions = item.get('definitions', [])
        for target_def in definitions:
            # target_def has 'entries' which contains the content?
            # Example: "definitions": [ { "dictionary": "...", "entries": [ { "type": "structured-content", "content": ... } ] } ]
            
            dict_name = target_def.get('dictionaryAlias') or target_def.get('dictionary', 'Unknown')
            
            # Extract POS and other tags from definition tags (Yomitan style)
            # e.g. [{'name': 'n', 'category': 'partOfSpeech', ...}, {'name': 'hon', 'category': 'misc', ...}]
            def_pos = []
            for t in target_def.get('tags', []):
                if isinstance(t, dict):
                    tag_name = t.get('name')
                    if tag_name:
                        def_pos.append(tag_name)
                elif isinstance(t, str):
                    def_pos.append(t)
            
            # Glosses from 'entries'
            glosses = []
            raw_html_parts = []
            style_blocks = []

            def add_style_block(style_value):
                if not style_value:
                    return
                if isinstance(style_value, str):
                    style_blocks.append(f"<style>{style_value}</style>")
                    return
                if isinstance(style_value, list):
                    for s in style_value:
                        add_style_block(s)
                    return
                if isinstance(style_value, dict):
                    # Some payloads use {"content": "..."} or {"css": "..."}.
                    for key in ('content', 'css', 'style'):
                        if key in style_value:
                            add_style_block(style_value.get(key))
                            return

            # Some APIs provide CSS at definition level.
            for style_key in ('style', 'styles', 'css', 'stylesheet'):
                if style_key in target_def:
                    add_style_block(target_def.get(style_key))

            def_entries = target_def.get('entries', [])
            for de in def_entries:
                if isinstance(de, dict) and de.get('type') == 'structured-content':
                     # Use shared renderer
                     html_list = structured_content.handle_structured_content(de)
                     glosses.extend(html_list)
                     raw_html_parts.extend(html_list)
                     # Some payloads attach CSS inside the structured-content entry.
                     for style_key in ('style', 'styles', 'css', 'stylesheet'):
                         if style_key in de:
                             add_style_block(de.get(style_key))
                elif isinstance(de, dict) and de.get('type') in ('style', 'stylesheet', 'css'):
                    add_style_block(de.get('content') or de.get('style') or de.get('css'))
                else:
                    # fallback
                    de_text = str(de)
                    glosses.append(de_text)
                    raw_html_parts.append(html.escape(de_text).replace("\n", "<br>"))
            
            if glosses:
                raw_html = "<br>".join(part for part in raw_html_parts if part)
                if style_blocks:
                    raw_html = f"{raw_html}{''.join(style_blocks)}"

                # Deduplicate Senses within this entry
                # (Yomitan can return split definitions that are actually identical)
                is_existing = False
                for s in senses:
                    if s['glosses'] == glosses:
                        # Append source if different? For now, just dedup.
                        # Merge POS triggers
                        s['pos'] = sorted(list(set(s['pos'] + def_pos)))
                        is_existing = True
                        break
                
                if not is_existing:
                    senses.append({
                        'glosses': glosses,
                        'pos': def_pos, # Use specific POS from this definition
                        'source': dict_name,
                        'raw_html': raw_html
                    })
        
        if not senses:
            # Check if there are pronunciations (pitch accent) even if no definitions
            # Some entries might only have pitch info if they are secondary
            pass

        # Extract Pronunciations (Pitch Accent)
        pronunciations = item.get('pronunciations', [])
        for pron in pronunciations:
            # pron structure: { "dictionary": "...", "dictionaryAlias": "...", "pronunciations": [ { "position": 2, ... } ] }
            d_name = pron.get('dictionaryAlias') or pron.get('dictionary', 'Unknown')
            
            # Format the pitch info strings
            pitch_glosses = []
            for p_data in pron.get('pronunciations', []):
                # Format: "PITCH:[position]:reading"
                target_reading = p_data.get('reading') or reading
                pos = p_data.get('positions')
                
                if pos is not None and target_reading:
                    # Wrap position in brackets to match Yomitan format
                    pitch_glosses.append(f"PITCH:[{pos}]:{target_reading}")
            
            if pitch_glosses:
                senses.append({
                    'glosses': pitch_glosses,
                    'pos': [],
                    'source': d_name
                })
        
        # --- Post-processing: Extract POS from ALL Headwords ---
        # Yomitan often puts POS in 'wordClasses' of the headword.
        # We also check 'tags' for common POS markers if wordClasses is empty.
        all_pos = set()
        
        # 1. Collect from wordClasses of all headwords
        for h in headwords:
            for wc in h.get('wordClasses', []):
                all_pos.add(wc)
                
            # 2. Heuristic: Check tags for common POS indicators if they look like POS
            for t in h.get('tags', []):
                tag_name = t.get('name', t) if isinstance(t, dict) else t
                if isinstance(tag_name, str):
                    # Common JMdict POS tags are often short codes or explicit names
                    lower_t = tag_name.lower()
                    if lower_t in ['n', 'noun', 'v1', 'v5', 'adj-i', 'adj-na', 'adv', 'uk', 'vk', 'vs']:
                         all_pos.add(tag_name)

        sorted_pos = sorted(list(all_pos))
        for sense in senses:
            is_pitch = any("PITCH:" in g for g in sense.get('glosses', []))
            if not is_pitch:
                 current_pos = sense.get('pos', [])
                 # Union and strict deduplication
                 new_pos = sorted(list(set(current_pos + sorted_pos)))
                 sense['pos'] = new_pos

        if not senses:
            return None

        # --- Extract Deconjugation Process from ALL Headwords ---
        deconjugation_process = []
        for h in headwords:
            sources = h.get('sources', [])
            for src in sources:
                # content = src.get('content') # e.g. "tabemashita"
                # Check 'reasons' or 'rules' or 'deinflectionRules'
                reasons = src.get('reasons') or src.get('rules') or []
                if isinstance(reasons, list):
                    for r in reasons:
                        if r not in deconjugation_process:
                             deconjugation_process.append(r)
        
        if not deconjugation_process:
            # Fallback A: Check 'inflectionRuleChainCandidates' (Yomitan API specific)
            # This contains the algorithmic rules used to deinflect the term.
            candidates = item.get('inflectionRuleChainCandidates', [])
            
            path_strings = []
            for candidate in candidates:
                rules = candidate.get('inflectionRules', [])
                # Extract rule names for this specific candidate chain
                # Replace standard hyphen with non-breaking hyphen to prevent wrapping (e.g. "- \n te")
                chain_steps = [r.get('name').replace('-', '&#8209;') for r in rules if r.get('name')]
                
                if chain_steps:
                    # User requested format: "passive < tara"
                    # We reverse it? No, usually rules are applied Source -> Target or Target -> Source?
                    # API returns rules in order of application or un-application?
                    # Usually "Tabemashita" -> [Polite, Past].
                    # If we show "Polite < Past", it implies order.
                    # User example: "passive < tara < potential".
                    # Let's assumes API order is correct.
                    # ESCAPE HEADERS for HTML display in Popup
                    path_str = " &lt; ".join(chain_steps)
                    if path_str not in path_strings:
                        path_strings.append(path_str)
            
            if path_strings:
                # Join multiple ambiguous paths with " / "
                final_str = " / ".join(path_strings)
                # We wrap in a single-element list so the Popup's " ← ".join() 
                # effectively does nothing to our internal formatting.
                deconjugation_process = [final_str]
        
        if not deconjugation_process:
            # Fallback B: if no reasons/rules found (api quirk?), but text differs, show "from original"
            for h in headwords:
                sources = h.get('sources', [])
                for src in sources:
                     orig = src.get('originalText', '').strip()
                     deinf = src.get('deinflectedText', '').strip()
                     
                     
                     
                     # If they differ and deinflected matches our entry headword (approx), it's a valid deinflection
                     if orig and deinf and orig != deinf:
                         deconjugation_process.append(f"from {orig}")

                         break # Only show one primary source
        
        # Convert to tuple for DictionaryEntry
        deconjugation_tuple = tuple(deconjugation_process)

        return DictionaryEntry(
            id=index, # arbitrary ID
            written_form=written_form,
            reading=reading,
            senses=senses,
            tags=tags,
            frequency_tags=frequency_tags,
            deconjugation_process=deconjugation_tuple
        )
