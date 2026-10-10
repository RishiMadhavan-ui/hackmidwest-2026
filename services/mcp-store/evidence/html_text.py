"""Pull text out of raw HTML, keeping track of what a human couldn't see.

The shopper's browse tool returns everything (visible, hidden, comments, alt
and aria text) because that's what makes the demo injection land. Provenance
uses the same pass to flag the hidden parts as evidence.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

# Elements with no closing tag; they never go on the open-element stack.
_VOID = {
  "area", "base", "br", "col", "embed", "hr", "img", "input",
  "link", "meta", "source", "track", "wbr",
}  # fmt: skip
_SKIP_CONTENT = {"script", "style", "noscript", "template"}
_TEXT_ATTRS = ("alt", "title", "aria-label", "placeholder")

# Inline styles that hide text from a person looking at the page.
_HIDING_STYLES = [
  re.compile(r"display\s*:\s*none"),
  re.compile(r"visibility\s*:\s*hidden"),
  re.compile(r"opacity\s*:\s*0(\.0+)?\s*(;|$)"),
  re.compile(r"font-size\s*:\s*0(px|pt|em|rem|%)?\s*(;|$)"),
  re.compile(r"(?<![-\w])color\s*:\s*(#fff(fff)?|white|transparent|rgba\([^)]*,\s*0\))"),
  re.compile(r"(left|top|right|bottom|text-indent)\s*:\s*-\d{3,}px"),
  re.compile(r"clip(-path)?\s*:\s*(rect\(0|inset\(50%)"),
  re.compile(r"(width|height)\s*:\s*0(px)?\s*;.*overflow\s*:\s*hidden"),
]


def _hides(attrs: dict[str, str | None]) -> str | None:
  """Return why an element is hidden, or None if it's visible."""
  if "hidden" in attrs:
    return "hidden attribute"
  if (attrs.get("aria-hidden") or "").lower() == "true":
    return "aria-hidden"
  style = (attrs.get("style") or "").lower()
  for pattern in _HIDING_STYLES:
    if pattern.search(style):
      return f"style: {pattern.pattern}"
  return None


@dataclass
class PageText:
  visible: list[str] = field(default_factory=list)
  hidden: list[tuple[str, str]] = field(default_factory=list)  # (text, why hidden)
  comments: list[str] = field(default_factory=list)
  attributes: list[str] = field(default_factory=list)

  def all_text(self) -> str:
    """Everything, in one string, the way a naive scraper would see it."""
    parts = [*self.visible, *(t for t, _ in self.hidden), *self.attributes, *self.comments]
    return "\n".join(parts)


class _Extractor(HTMLParser):
  def __init__(self) -> None:
    super().__init__(convert_charrefs=True)
    self.page = PageText()
    # Each open element: (tag, why hidden or None, skips content)
    self.stack: list[tuple[str, str | None, bool]] = []

  def _hidden_reason(self) -> str | None:
    for _, why, _ in reversed(self.stack):
      if why:
        return why
    return None

  def _skipping(self) -> bool:
    return any(skip for _, _, skip in self.stack)

  def handle_starttag(self, tag, attrs):
    attr_map = {k.lower(): v for k, v in attrs}
    for name in _TEXT_ATTRS:
      value = (attr_map.get(name) or "").strip()
      if value:
        self.page.attributes.append(value)
    if tag not in _VOID:
      self.stack.append((tag, _hides(attr_map), tag in _SKIP_CONTENT))

  def handle_startendtag(self, tag, attrs):
    attr_map = {k.lower(): v for k, v in attrs}
    for name in _TEXT_ATTRS:
      value = (attr_map.get(name) or "").strip()
      if value:
        self.page.attributes.append(value)

  def handle_endtag(self, tag):
    # Real pages leave tags unclosed; pop back to the matching open tag if any.
    for i in range(len(self.stack) - 1, -1, -1):
      if self.stack[i][0] == tag:
        del self.stack[i:]
        return

  def handle_data(self, data):
    text = " ".join(data.split())
    if not text or self._skipping():
      return
    why = self._hidden_reason()
    if why:
      self.page.hidden.append((text, why))
    else:
      self.page.visible.append(text)

  def handle_comment(self, data):
    text = " ".join(data.split())
    if text:
      self.page.comments.append(text)


def extract(html: str) -> PageText:
  parser = _Extractor()
  parser.feed(html)
  parser.close()
  return parser.page
