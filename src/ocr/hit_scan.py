# src/ocr/hit_scan.py
import logging
import re
import threading
from typing import List

from src.gui.magpie_manager import magpie_manager
from src.ocr.interface import Paragraph

logger = logging.getLogger(__name__)  # Get the logger

KANJI_REGEX = re.compile(r'[\u4e00-\u9faf]')
KANA_REGEX = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]')


class HitScanner(threading.Thread):
    def __init__(self, shared_state, input_loop, screen_manager):
        super().__init__(daemon=True, name="HitScanner")
        self.shared_state = shared_state
        self.input_loop = input_loop
        self.screen_manager = screen_manager
        self.last_ocr_result = None

    def run(self):
        logger.debug("HitScanner thread started.")
        while self.shared_state.running:
            try:
                is_ocr_result_updated, new_ocr_result = self.shared_state.hit_scan_queue.get()
                if not self.shared_state.running: break
                logger.debug("HitScanner: Triggered")

                if is_ocr_result_updated:
                    self.last_ocr_result = new_ocr_result

                hit_scan_result = self.hit_scan(self.last_ocr_result) if self.last_ocr_result else None

                # Trigger the lookup
                self.shared_state.lookup_queue.put(hit_scan_result)
            except:
                logger.exception("An unexpected error occurred in the hit scan loop. Continuing...")
        logger.debug("HitScanner thread stopped.")

    def hit_scan(self, paragraphs: List[Paragraph]):
        mouse_x, mouse_y = magpie_manager.transform_raw_to_visual(self.input_loop.get_mouse_pos(), 1)
        mouse_off_x, mouse_off_y, img_w, img_h = self.screen_manager.get_scan_geometry()
        relative_x = mouse_x - mouse_off_x
        relative_y = mouse_y - mouse_off_y
        norm_x, norm_y = relative_x / img_w, relative_y / img_h

        def is_in_box(point, box):
            if not box: return False
            px, py = point
            half_w, half_h = box.width / 2, box.height / 2
            return (box.center_x - half_w <= px <= box.center_x + half_w) and \
                (box.center_y - half_h <= py <= box.center_y + half_h)

        def is_in_box_ex(point, box_before, box, box_after, is_vertical_flag):
            if not box: return False
            left = box.center_x - box.width / 2
            right = box.center_x + box.width / 2
            top = box.center_y - box.height / 2
            bottom = box.center_y + box.height / 2
            if not is_vertical_flag and box_before: left = min(left, box_before.center_x + box_before.width / 2)
            if not is_vertical_flag and box_after: right = max(right, box_after.center_x - box_after.width / 2)
            if is_vertical_flag and box_before: top = min(top, box_before.center_y + box_before.height / 2)
            if is_vertical_flag and box_after: bottom = max(bottom, box_after.center_y - box_after.height / 2)
            px, py = point
            return (left <= px <= right) and (top <= py <= bottom)

        hit_scan_result = None
        lookup_string = None
        context_text = None

        for para in paragraphs:
            if not is_in_box((norm_x, norm_y), para.box):
                continue

            target_word = None
            para_box_abs_w = para.box.width * img_w
            para_box_abs_h = para.box.height * img_h
            is_vertical = para.is_vertical or para_box_abs_h > para_box_abs_w
            words = list(para.words)

            for i, word in enumerate(words):
                box_before = words[i - 1].box if i > 0 else None
                box_after = words[i + 1].box if i < len(words) - 1 else None
                if is_in_box_ex((norm_x, norm_y), box_before, word.box, box_after, is_vertical):
                    target_word = word
                    break

            if not target_word:
                continue

            char_offset = 0

            if is_vertical:
                if target_word.box.height > 0:
                    top_edge = target_word.box.center_y - (target_word.box.height / 2)
                    relative_y_in_box = norm_y - top_edge
                    char_percent = max(0.0, min(relative_y_in_box / target_word.box.height, 1.0))
                    char_offset = int(char_percent * len(target_word.text))
            else:  # Horizontal
                if target_word.box.width > 0:
                    left_edge = target_word.box.center_x - (target_word.box.width / 2)
                    relative_x_in_box = norm_x - left_edge
                    char_percent = max(0.0, min(relative_x_in_box / target_word.box.width, 1.0))
                    char_offset = int(char_percent * len(target_word.text))

            char_offset = min(char_offset, len(target_word.text) - 1)

            word_start_index = 0
            for word in para.words:
                if word is target_word:
                    break
                word_start_index += len(word.text)

            final_char_index = word_start_index + char_offset
            full_text = para.full_text

            if final_char_index >= len(full_text):
                continue

            character = full_text[final_char_index]
            # Extract lookup string: start from beginning of current word
            # Stop at separators, word boundaries, or after reasonable length
            JAPANESE_SEPARATORS = {"、", "。", "「", "」", "｛", "｝", "（", "）", "【", "】", "『", "』", "〈", "〉", "《", "》", "：", "・", "／",
                                   "…", "︙", "‥", "︰", "＋", "＝", "－", "÷", "？", "！", "．", "～", "―", "!", "?"}
            
            # Find the index of target_word in the words list and calculate next word boundary
            target_word_index = None
            for idx, word in enumerate(words):
                if word is target_word:
                    target_word_index = idx
                    break
            
            # Start from the beginning of the current word
            word_start_char_index = word_start_index
            # Include the current word fully - this is our base lookup_end
            lookup_end = word_start_char_index + len(target_word.text)

            # Detect compound words: if next word starts immediately after current word (no separator),
            # and it's kanji/kana (not a particle), include it as part of the compound
            # Common particles that separate words: の、を、に、が、は、で、と、から、まで、より、へ
            JAPANESE_PARTICLES = {"の", "を", "に", "が", "は", "で", "と", "から", "まで", "より", "へ", "も", "や", "か"}

            # Greedy Compound Merging

            # Iterate forward from the target word to merge valid adjacent words (e.g. Tabe + Mashita)
            curr_word_idx = target_word_index
            curr_lookup_end = lookup_end
            
            # Start tracking the end of the previous word to detect gaps
            last_word_end_index = word_start_char_index + len(target_word.text) 
            
            # We need to know the start index of subsequent words relative to full_text.
            # Since words list doesn't have absolute indices, we must continue counting from where we are.
            # word_start_index currently points to start of target_word.
            
            # Helper: Get start index of word at `idx` in words list (assuming contiguous if we just sum lengths? 
            # NO, if full_text has spaces, summing lengths is WRONG if separators are missing from len).
            # But we are constrained by existing logic: `final_char_index` used `word_start_index`.
            # If existing logic is correct, `full_text` IS contiguous words?
            # Let's assume we can scan forward in `full_text` looking for the next word text.
            
            while curr_word_idx is not None and curr_word_idx < len(words) - 1:
                next_word = words[curr_word_idx + 1]
                
                # Find where this next word actually starts in full_text
                # It should be at or after `curr_lookup_end`
                # Heuristic: search for next_word.text in full_text[curr_lookup_end : curr_lookup_end + len + margin]
                search_start = curr_lookup_end
                # Allow a small gap (e.g. 1 space)
                search_limit = min(len(full_text), search_start + len(next_word.text) + 2) 
                
                found_idx = full_text.find(next_word.text, search_start, search_limit)
                
                if found_idx == -1:
                    # Could not find next word where expected? Stop.
                    break
                
                gap_size = found_idx - curr_lookup_end
                
                # Check for particles/compound validity
                if (next_word.text and
                    (KANJI_REGEX.search(next_word.text) or KANA_REGEX.search(next_word.text)) and
                    next_word.text not in JAPANESE_PARTICLES):
                    
                    # Accept merge
                    curr_lookup_end = found_idx + len(next_word.text)
                    curr_word_idx += 1
                else:
                    # Valid word but failed compound check (e.g. particle)
                    break
            
            lookup_end = curr_lookup_end
            
            lookup_string = full_text[final_char_index:lookup_end]
            
            # --- Context Extension Logic ---
            # OCR often splits sentences into multiple paragraph blocks. 
            # We try to merge aligned paragraphs to reconstruct the full line/sentence.
            
            merged_context = full_text
            
            if is_vertical:
                # Vertical Text: Look for paragraphs aligned vertically (similar center_X)
                # and sort them top-to-bottom (center_Y)
                aligned_paras = []
                x_tolerance = para.box.width * 0.5
                
                for p in paragraphs:
                    if abs(p.box.center_x - para.box.center_x) < x_tolerance:
                         aligned_paras.append(p)
                
                # Sort by Y position
                aligned_paras.sort(key=lambda p: p.box.center_y)
                merged_context = "\n".join([p.full_text for p in aligned_paras])
                
            else:
                # Horizontal Text: Look for paragraphs aligned horizontally (similar center_Y)
                # and sort them left-to-right (center_X)
                aligned_paras = []
                y_tolerance = para.box.height * 0.5
                
                for p in paragraphs:
                    if abs(p.box.center_y - para.box.center_y) < y_tolerance:
                        aligned_paras.append(p)
                
                # Sort by X position
                aligned_paras.sort(key=lambda p: p.box.center_x)
                # Join with space? Japanese usually doesn't need space, but if blocks are split...
                # safe to just join.
                merged_context = "".join([p.full_text for p in aligned_paras])

            context_text = merged_context
            
            hit_scan_result = (full_text, final_char_index, character,
                               lookup_string, para.box)  # Pass the box directly
            break

        if hit_scan_result:
            text, char_pos, char, lookup_string, context_box = hit_scan_result
            truncated_text = (text[:40] + '...') if len(text) > 40 else text
            
            return {
                "lookup_string": lookup_string,
                "context_text": context_text,
                "screenshot": self.screen_manager.last_screenshot,
                "context_box": context_box,
                "scan_geometry": self.screen_manager.get_scan_geometry()
            }

        return None
