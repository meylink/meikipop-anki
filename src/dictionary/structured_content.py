import html
import re
from typing import Any, List, Dict

ALLOWED_TAGS = {
    'a', 'abbr', 'b', 'big', 'blockquote', 'br', 'code', 'div', 'em', 'i', 'img',
    'li', 'mark', 'ol', 'p', 'pre', 'q', 'rp', 'rt', 'ruby', 's', 'small', 'span',
    'strong', 'style', 'sub', 'sup', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'u', 'ul'
}

ALLOWED_ATTRS = {
    'alt', 'aria-label', 'class', 'colspan', 'href', 'id', 'lang', 'rel', 'rowspan',
    'src', 'style', 'target', 'title', 'width', 'height'
}

def escape_html(text: str) -> str:
    return html.escape(text, quote=True)


def _camel_to_kebab(name: str) -> str:
    return re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()


def _build_style(style_obj: Any) -> str:
    if isinstance(style_obj, str):
        return style_obj.strip()
    if not isinstance(style_obj, dict):
        return ""

    parts = []
    for key, value in style_obj.items():
        if value is None:
            continue
        css_key = _camel_to_kebab(str(key))
        parts.append(f"{css_key}: {value}")
    return "; ".join(parts)


def _sanitize_url(value: str) -> str:
    low = value.strip().lower()
    if low.startswith('javascript:'):
        return ""
    return value


def _normalize_attr_name(attr_name: str) -> str:
    # Common DOM-like names from structured content payloads.
    if attr_name == 'className':
        return 'class'
    if attr_name == 'htmlFor':
        return 'for'

    # scContent/scClass/scCode -> data-sc-content/data-sc-class/data-sc-code
    if attr_name.startswith('sc') and len(attr_name) > 2 and attr_name[2].isupper():
        tail = _camel_to_kebab(attr_name[2:])
        return f'data-sc-{tail}'

    # dataScContent -> data-sc-content
    if attr_name.startswith('data') and len(attr_name) > 4 and attr_name[4].isupper():
        return 'data-' + _camel_to_kebab(attr_name[4:])

    # sc-content -> data-sc-content
    if attr_name.startswith('sc-'):
        return 'data-' + attr_name

    return attr_name


def _extract_attributes(node: Dict[str, Any]) -> str:
    attrs: Dict[str, str] = {}

    # Some payloads keep attributes in node['data'], others at node top level.
    attr_sources = []
    data = node.get('data')
    if isinstance(data, dict):
        attr_sources.append(data)

    top_level = {k: v for k, v in node.items() if k not in ('tag', 'content', 'data', 'type')}
    if top_level:
        attr_sources.append(top_level)

    for source in attr_sources:
        for key, value in source.items():
            if value is None:
                continue

            raw_name = str(key)
            if raw_name.lower().startswith('on'):
                continue

            attr_name = _normalize_attr_name(raw_name)

            if attr_name in ('style', 'styles'):
                style_str = _build_style(value)
                if style_str:
                    attrs['style'] = style_str
                continue

            # Preserve arbitrary data-* and aria-* attributes used by Yomitan rendering.
            if attr_name.startswith('data-') or attr_name.startswith('aria-'):
                attrs[attr_name] = str(value)
                continue

            if attr_name not in ALLOWED_ATTRS:
                continue

            if attr_name in ('href', 'src'):
                safe_url = _sanitize_url(str(value))
                if not safe_url:
                    continue
                attrs[attr_name] = safe_url
                continue

            attrs[attr_name] = str(value)

    if not attrs:
        return ""

    parts = [f'{k}="{escape_html(v)}"' for k, v in attrs.items()]
    return " " + " ".join(parts)

def render_node(node: Any) -> str:
    """Recursively render a structured content node to HTML."""
    if isinstance(node, str):
        return escape_html(node)
    
    if isinstance(node, list):
        return "".join(render_node(child) for child in node)
        
    if isinstance(node, dict):
        # Handle "content" being list or string
        content_obj = node.get('content')
        inner_html = ""
        if content_obj:
            inner_html = render_node(content_obj)
            
        tag = node.get('tag')
        if not tag:
            return inner_html

        tag = str(tag).lower().strip()
        if tag not in ALLOWED_TAGS:
            # Fallback for unknown tags: return content
            return inner_html

        attr_str = _extract_attributes(node)
            
        # Map tags to HTML
        # Supported subset by Qt: span, div, p, br, table, tr, td, ul, ol, li, b, i, u, s, img, sub, sup, etc.
        if tag == 'br':
            return "<br>"
        elif tag == 'img':
            return f"<img{attr_str}>"
        else:
            return f"<{tag}{attr_str}>{inner_html}</{tag}>"

    return ""

def handle_structured_content(item: Dict[str, Any]) -> List[str]:
    """
    Process dictionary item identified as 'structured-content'.
    Returns a list containing a single HTML string.
    """
    content = item.get('content')
    html_output = render_node(content)
    if html_output:
        return [html_output]
    return []
