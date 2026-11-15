"""Sampled or partial coverage remains visible with disclosures closed."""
from html.parser import HTMLParser
import re

import pytest


class VisibleGroup(HTMLParser):
    """Read a named accessible group without scripts or closed details."""

    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self, markup, label):
        super().__init__()
        self.label, self.stack, self.words = label, [], []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        parent_hidden, parent_group = self.stack[-1][1:] if self.stack else (False, False)
        hidden = parent_hidden or "hidden" in attrs or attrs.get("aria-hidden") == "true" or tag in {"script", "style"} or (tag == "details" and "open" not in attrs)
        group = parent_group or (attrs.get("role") == "group" and attrs.get("aria-label") == self.label)
        if tag not in self.void:
            self.stack.append((tag, hidden, group))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, text):
        if self.stack and not self.stack[-1][1] and self.stack[-1][2]:
            self.words.append(text)

    @property
    def text(self):
        return " ".join(" ".join(self.words).split())


@pytest.mark.parametrize("complete,scope", [(False, "Partial"), (True, "Complete")])
def test_temporal_overview_exposes_sample_fraction_and_declared_search(complete, scope):
    from test_report import report
    from tradeoff.report import render_report

    data = report("NO_DEPENDENCY_OBSERVED")
    data["coverage"].update(cutoffs_probed=2, eligible_cutoffs=19, complete=complete)
    text = VisibleGroup(render_report(data), "Audit coverage").text
    assert re.search(r"\b2\s*/\s*19\b", text), "Sampled and eligible cutoffs must be visible together"
    assert scope in text


@pytest.mark.parametrize("complete,total,scope", [(False, 3, "Partial"), (True, 1, "Complete")])
def test_native_overview_exposes_completed_fraction_and_suite_state(complete, total, scope):
    from test_failure_report import sample_report
    from tradeoff.report.failure_renderer import render_failure_report

    data = sample_report()
    data["coverage"].update(completed=1, total=total, complete=complete)
    text = VisibleGroup(render_failure_report(data), "Execution coverage").text
    assert re.search(rf"\b1\s*/\s*{total}\b", text), "Completed and declared scenarios must be visible together"
    assert scope in text
