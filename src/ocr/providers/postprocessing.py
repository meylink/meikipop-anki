# src/ocr/providers/postprocessing.py
import logging
import statistics
from typing import List, Tuple

from src.ocr.interface import Paragraph, Word, BoundingBox

logger = logging.getLogger(__name__)

FURIGANA_VERTICAL_WIDTH_THRESHOLD = 0.65
FURIGANA_HORIZONTAL_HEIGHT_THRESHOLD = 0.65


def _merge_bounding_boxes(boxes: List[BoundingBox]) -> BoundingBox:
    """Creates a single BoundingBox that encompasses all provided boxes."""
    if not boxes:
        return BoundingBox(0, 0, 0, 0)

    min_x = min(b.center_x - b.width / 2 for b in boxes)
    max_x = max(b.center_x + b.width / 2 for b in boxes)
    min_y = min(b.center_y - b.height / 2 for b in boxes)
    max_y = max(b.center_y + b.height / 2 for b in boxes)

    width = max_x - min_x
    height = max_y - min_y
    center_x = min_x + width / 2
    center_y = min_y + height / 2

    return BoundingBox(center_x, center_y, width, height)


def _are_lines_adjacent(line1: Paragraph, line2: Paragraph) -> bool:
    """
    Determines if two lines are close enough to be considered part of the same paragraph.
    This uses heuristics to be tolerant of small OCR inaccuracies.
    """
    b1, b2 = line1.box, line2.box
    is_vertical = line1.is_vertical

    if is_vertical:
        # For vertical text (read R->L), lines should have significant y-overlap
        # and be close on the x-axis.
        y_overlap = max(0,
                        min(b1.center_y + b1.height / 2, b2.center_y + b2.height / 2) - max(b1.center_y - b1.height / 2,
                                                                                            b2.center_y - b2.height / 2))
        has_enough_overlap = y_overlap > (min(b1.height, b2.height) * 0.5)

        # Check horizontal distance between line centers. Allow up to 1.9x the width of a line for spacing.
        horizontal_distance_ok = abs(b1.center_x - b2.center_x) < 1.9 * max(b1.width, b2.width)
        return has_enough_overlap and horizontal_distance_ok
    else:
        # For horizontal text (read T->B), lines should have significant x-overlap
        # and be close on the y-axis.
        x_overlap = max(0, min(b1.center_x + b1.width / 2, b2.center_x + b2.width / 2) - max(b1.center_x - b1.width / 2,
                                                                                             b2.center_x - b2.width / 2))
        has_enough_overlap = x_overlap > (min(b1.width, b2.width) * 0.5)

        # Check vertical distance. Allow up to 1.9x the height for line spacing.
        vertical_distance_ok = abs(b1.center_y - b2.center_y) < 1.9 * max(b1.height, b2.height)
        return has_enough_overlap and vertical_distance_ok


def _merge_lines_into_paragraph(lines: List[Paragraph]) -> Paragraph:
    """Merges a list of single-line Paragraphs into one cohesive Paragraph."""
    if not lines:
        return None

    is_vertical = lines[0].is_vertical

    if is_vertical:
        # Vertical text is read right-to-left
        lines.sort(key=lambda p: p.box.center_x, reverse=True)
    else:
        # Horizontal text is read top-to-bottom
        lines.sort(key=lambda p: p.box.center_y)

    all_words: List[Word] = []
    full_text_parts: List[str] = []
    all_boxes: List[BoundingBox] = []

    for line in lines:
        all_words.extend(line.words)
        full_text_parts.append(line.full_text)
        all_boxes.append(line.box)

    full_text = "".join(full_text_parts)
    merged_box = _merge_bounding_boxes(all_boxes)

    return Paragraph(
        full_text=full_text,
        words=all_words,
        box=merged_box,
        is_vertical=is_vertical
    )


# NEW FUNCTION TO DETECT FURIGANA
def _classify_lines_by_size(
        lines: List[Paragraph]
) -> Tuple[List[Paragraph], List[Paragraph]]:
    """
    Separates lines into main text and furigana based on their size.

    Furigana is much smaller than the main text. This function calculates the
    median size (width for vertical, height for horizontal) and classifies
    any significantly smaller lines as furigana.

    Returns:
        A tuple containing two lists: (main_lines, furigana_lines).
    """
    main_lines: List[Paragraph] = []
    furigana_lines: List[Paragraph] = []

    vertical_lines = [p for p in lines if p.is_vertical]
    horizontal_lines = [p for p in lines if not p.is_vertical]

    if vertical_lines:
        # For vertical text, furigana lines are much thinner (smaller width)
        widths = [p.box.width for p in vertical_lines]
        if len(widths) > 1:
            median_width = statistics.median(widths)
            threshold = median_width * FURIGANA_VERTICAL_WIDTH_THRESHOLD
            for line in vertical_lines:
                if line.box.width < threshold:
                    furigana_lines.append(line)
                else:
                    main_lines.append(line)
        else:
            # If there's only one line, it's main text by definition
            main_lines.extend(vertical_lines)

    if horizontal_lines:
        # For horizontal text, furigana lines are much shorter (smaller height)
        heights = [p.box.height for p in horizontal_lines]
        if len(heights) > 1:
            median_height = statistics.median(heights)
            threshold = median_height * FURIGANA_HORIZONTAL_HEIGHT_THRESHOLD
            for line in horizontal_lines:
                if line.box.height < threshold:
                    furigana_lines.append(line)
                else:
                    main_lines.append(line)
        else:
            main_lines.extend(horizontal_lines)

    return main_lines, furigana_lines


def group_lines_into_paragraphs(lines: List[Paragraph]) -> List[Paragraph]:
    """
    Takes a flat list of single-line Paragraphs and groups them into
    multi-line Paragraphs based on proximity and orientation.

    This version includes a preprocessing step to identify and separate
    furigana, which is then excluded from the main paragraph grouping logic.
    """
    if not lines:
        return []

    # Classify lines into main text and furigana
    main_lines, furigana_lines = _classify_lines_by_size(lines)
    logger.debug(f"Identified and separated {len(furigana_lines)} furigana lines.")

    # Separate main lines by orientation for processing
    vertical_lines = [p for p in main_lines if p.is_vertical]
    horizontal_lines = [p for p in main_lines if not p.is_vertical]

    processed_paragraphs: List[Paragraph] = []

    def process_lines(lines_subset: List[Paragraph]):
        """
        Groups a subset of lines (either all vertical or all horizontal)
        using a graph-based connected components approach (BFS).
        Complexity: O(N^2) to build graph, O(N) to traverse.
        """
        n = len(lines_subset)
        if n == 0:
            return

        # 1. Build Adjacency Graph (Adjacency List)
        # adj[i] = [list of indices j that are adjacent to i]
        adj = [[] for _ in range(n)]

        # O(N^2) comparison to find all adjacent pairs
        # This is acceptable for N <= 500 roughly.
        for i in range(n):
            for j in range(i + 1, n):
                if _are_lines_adjacent(lines_subset[i], lines_subset[j]):
                    adj[i].append(j)
                    adj[j].append(i)

        # 2. Find Connected Components via BFS
        visited = [False] * n
        for i in range(n):
            if not visited[i]:
                # Start a new component
                component_indices = []
                queue = [i]
                visited[i] = True
                
                while queue:
                    u = queue.pop(0)
                    component_indices.append(u)
                    
                    for v in adj[u]:
                        if not visited[v]:
                            visited[v] = True
                            queue.append(v)
                
                # 3. Merge this component into a single paragraph
                component_lines = [lines_subset[idx] for idx in component_indices]
                merged_para = _merge_lines_into_paragraph(component_lines)
                if merged_para:
                    processed_paragraphs.append(merged_para)

    # Process vertical and horizontal lines separately
    process_lines(vertical_lines)
    process_lines(horizontal_lines)

    # Add the isolated furigana lines back as their own separate paragraphs
    final_paragraphs = processed_paragraphs + furigana_lines

    logger.debug(f"Regrouped {len(lines)} raw OCR lines into {len(final_paragraphs)} paragraphs.")
    return final_paragraphs
