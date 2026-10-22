"""Phase D: runtime element discovery.

Given a target (plain text, an explicit locator, or '<column> cell of <row>'),
find the one visible element it describes on the live page. This module only
locates elements. It never clicks, types, or reads values.

- Searches the main page, then every frame (iframes included).
- Plain text tries roles, then label, placeholder, and visible text.
  Exact name matches are tried before substring matches.
- Hidden elements are ignored.
- More than one visible match returns AMBIGUOUS and stops. Nothing is picked silently.
"""
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

FOUND = "found"
AMBIGUOUS = "ambiguous"
MISSING = "missing"

EXPLICIT = re.compile(
    r"^(?P<kind>role|label|placeholder|text|css|xpath|testid|id|alt|title)=(?P<rest>.+)$",
    re.IGNORECASE,
)
GRID = re.compile(r"^(?P<col>.+?)\s+cell\s+of\s+(?P<row>.+)$", re.IGNORECASE)
TOKEN_ATTR = "data-verity-target"

GRID_JS = r"""
([col, row, token]) => {
  document.querySelectorAll('[' + 'data-verity-target' + ']').forEach(e => e.removeAttribute('data-verity-target'));
  const shown = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const txt = e => (e.innerText || '').trim().replace(/\s+/g, ' ');
  const lc = s => s.toLowerCase();
  const mid = e => { const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; };
  const all = [...document.querySelectorAll('body *')].filter(shown);

  // Innermost matches. If they sit at different positions, the target is ambiguous.
  const pick = matches => {
    if (!matches.length) return { none: true };
    const inner = matches.filter(e => !matches.some(o => o !== e && e.contains(o)));
    const spots = new Set(inner.map(e => { const c = mid(e); return Math.round(c.x) + ',' + Math.round(c.y); }));
    return spots.size > 1 ? { ambiguous: spots.size } : { el: inner[0] };
  };

  const c = lc(col);
  const headers = pick(all.filter(e => {
    const t = txt(e);
    return t.length <= col.length + 12 && lc(t).startsWith(c)
      && (t.length === col.length || /[\s\-\/\d]/.test(t.charAt(col.length)));
  }));
  if (headers.none) return { status: 'missing', reason: "no column heading '" + col + "' on the page" };
  if (headers.ambiguous) return { status: 'ambiguous', reason: "column heading '" + col + "' appears " + headers.ambiguous + ' times' };

  let rows = pick(all.filter(e => lc(txt(e)) === lc(row)));
  if (rows.none) rows = pick(all.filter(e => lc(txt(e)).includes(lc(row))));
  if (rows.none) return { status: 'missing', reason: "no row labelled '" + row + "'" };
  if (rows.ambiguous) return { status: 'ambiguous', reason: "row label '" + row + "' appears " + rows.ambiguous + ' times' };

  const hc = mid(headers.el);
  const rc = mid(rows.el);
  const rh = rows.el.getBoundingClientRect().height;
  const skip = ['hidden', 'checkbox', 'radio', 'button', 'submit', 'reset', 'image', 'file'];
  let best = null;
  let bestScore = Infinity;
  for (const input of document.querySelectorAll('input, textarea')) {
    if (!shown(input) || skip.includes(input.type)) continue;
    const c2 = mid(input);
    const dy = Math.abs(c2.y - rc.y);
    if (dy > (rh + input.getBoundingClientRect().height) / 2) continue;
    const score = Math.abs(c2.x - hc.x) + dy;
    if (score < bestScore) { bestScore = score; best = input; }
  }
  if (!best) return { status: 'missing', reason: "no input under '" + col + "' on the row '" + row + "'" };
  best.setAttribute('data-verity-target', token);
  return { status: 'found', reason: '' };
}
"""


@dataclass
class Discovery:
    status: str                  # found, ambiguous, or missing
    locator: Any = None          # a Playwright Locator resolving to one element, when found
    strategy: str = ""           # which rule found it, for diagnostics
    count: int = 0               # number of visible matches
    reason: str = ""             # why it is missing or ambiguous
    frame: Any = None            # the frame the element was found in

    @property
    def ok(self):
        return self.status == FOUND


def _first_line(error):
    lines = str(error).strip().splitlines()
    return lines[0] if lines else error.__class__.__name__


def _settle(strategy, locator, frame):
    visible = locator.filter(visible=True)
    count = visible.count()
    if count == 1:
        return Discovery(FOUND, visible.first, strategy, 1, "", frame)
    if count > 1:
        return Discovery(AMBIGUOUS, None, strategy, count,
                         f"{count} visible elements match via {strategy}; refusing to pick one", frame)
    return Discovery(MISSING, None, strategy, 0, f"no visible match via {strategy}", frame)


def _flexible_pat(name):
    clean = name.lstrip("* ").strip()
    parts = re.findall(r"[A-Za-z][a-z]*|[0-9]+", clean)
    if not parts:
        parts = [clean]
    joined = r"\s*".join(re.escape(p) for p in parts)
    return re.compile(rf"^\*?\s*{joined}$", re.IGNORECASE)


def _plain(frame, name):
    pat = _flexible_pat(name)
    for exact in (True, False):
        if exact:
            candidates = [
                ("role:button", frame.get_by_role("button", name=name, exact=True)),
                ("role:button-pat", frame.get_by_role("button", name=pat)),
                ("role:link", frame.get_by_role("link", name=name, exact=True)),
                ("role:link-pat", frame.get_by_role("link", name=pat)),
                ("title", frame.get_by_title(name, exact=True)),
                ("alt", frame.get_by_alt_text(name, exact=True)),
                ("role:textbox", frame.get_by_role("textbox", name=name, exact=True)),
                ("role:textbox-pat", frame.get_by_role("textbox", name=pat)),
                ("role:combobox", frame.get_by_role("combobox", name=name, exact=True)),
                ("role:combobox-pat", frame.get_by_role("combobox", name=pat)),
                ("role:checkbox", frame.get_by_role("checkbox", name=name, exact=True)),
                ("label", frame.get_by_label(name, exact=True)),
                ("label-pat", frame.get_by_label(pat)),
                ("placeholder", frame.get_by_placeholder(name, exact=True)),
                ("placeholder-pat", frame.get_by_placeholder(pat)),
                ("aria-label", frame.locator(f'[aria-label="{name}" i]')),
                ("title-attr", frame.locator(f'[title="{name}" i]')),
                ("text", frame.get_by_text(name, exact=True)),
            ]
        else:
            candidates = [
                ("role:button", frame.get_by_role("button", name=name, exact=False)),
                ("role:link", frame.get_by_role("link", name=name, exact=False)),
                ("title", frame.get_by_title(name, exact=False)),
                ("alt", frame.get_by_alt_text(name, exact=False)),
                ("role:textbox", frame.get_by_role("textbox", name=name, exact=False)),
                ("role:combobox", frame.get_by_role("combobox", name=name, exact=False)),
                ("role:checkbox", frame.get_by_role("checkbox", name=name, exact=False)),
                ("label", frame.get_by_label(name, exact=False)),
                ("placeholder", frame.get_by_placeholder(name, exact=False)),
                ("aria-label", frame.locator(f'[aria-label*="{name}" i]')),
                ("title-attr", frame.locator(f'[title*="{name}" i]')),
                ("text", frame.get_by_text(name, exact=False)),
            ]
        if name.lower() == "home":
            candidates.append(("oracle-home", frame.locator("#pt1\\:_UIShome, [id*='_UIShome']")))
        for strategy, locator in candidates:
            result = _settle(strategy, locator, frame)
            if result.status != MISSING:
                return result
    return Discovery(MISSING, None, "", 0, f"no visible element matches '{name}'", frame)


def _explicit(frame, kind, rest):
    by_method = {
        "label": frame.get_by_label,
        "placeholder": frame.get_by_placeholder,
        "alt": frame.get_by_alt_text,
        "title": frame.get_by_title,
        "testid": frame.get_by_test_id,
    }
    if kind in by_method:
        locator = by_method[kind](rest, exact=True)
    else:
        # role=, text=, css=, xpath=, id= are Playwright selectors, passed through as written.
        locator = frame.locator(f"{kind}={rest}")
    return _settle(f"explicit:{kind}", locator, frame)


def _grid(frame, col, row):
    token = f"v{uuid.uuid4().hex[:10]}"
    outcome = frame.evaluate(GRID_JS, [col, row, token])
    if outcome["status"] != FOUND:
        return Discovery(outcome["status"], None, "grid", 0, outcome["reason"], frame)
    locator = frame.locator(f'[{TOKEN_ATTR}="{token}"]')
    return Discovery(FOUND, locator, "grid", 1, "", frame)


def _attempt(frame, target):
    grid = GRID.match(target)
    if grid:
        return _grid(frame, grid.group("col").strip(), grid.group("row").strip())
    explicit = EXPLICIT.match(target)
    if explicit:
        return _explicit(frame, explicit.group("kind").lower(), explicit.group("rest").strip())
    return _plain(frame, target)


def discover(page, target, timeout_ms=5000):
    """Find the single visible element described by target. Retries until timeout_ms.

    Returns a Discovery. Check .status: FOUND gives a usable .locator; AMBIGUOUS and
    MISSING never give one, so the caller cannot act on a guessed element.
    """
    deadline = time.time() + timeout_ms / 1000
    last = Discovery(MISSING, None, "", 0, f"no element matches '{target}'")
    while True:
        for frame in page.frames:
            try:
                result = _attempt(frame, target)
            except Exception as exc:
                result = Discovery(MISSING, None, "", 0,
                                   f"could not search a frame: {_first_line(exc)}", frame)
            if result.status in (FOUND, AMBIGUOUS):
                return result
            last = result
        if time.time() >= deadline:
            return last
        page.wait_for_timeout(250)


if __name__ == "__main__":
    import sys
    from playwright.sync_api import sync_playwright

    url, *targets = sys.argv[1:]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded")
        for target in targets:
            r = discover(page, target, timeout_ms=3000)
            detail = f" - {r.reason}" if r.reason else ""
            print(f"{target!r}: {r.status} via {r.strategy or '-'} (matches: {r.count}){detail}")
        browser.close()