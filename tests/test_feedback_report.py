import json
from html.parser import HTMLParser

from feedback_helpers import AFTER_HORIZON, episode_records
from test_feedback_export import export_fixture


class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.external = []
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {"src", "href"} and value and value.startswith(("http:", "https:", "//")):
                self.external.append(value)


def test_unknown_net_stays_unknown_and_all_views_exist_without_js(tmp_path):
    export_fixture(tmp_path, records=episode_records(short=True))
    page = (tmp_path / "feedback-output/index.html").read_text()
    for label in ("Data quality", "Decisions", "Outcomes", "Compare", "Evidence", "Cost coverage incomplete", "BORROW_COST_UNKNOWN"):
        assert label in page
    assert 'data-net-state="unknown"' in page
    parser = Document()
    parser.feed(page)
    assert parser.external == []
    assert 'href="#main"' in page


def test_untrusted_diagnostics_cannot_become_html_or_template_tokens(tmp_path):
    from tradeoff.report.feedback_renderer import render_feedback_report
    export_fixture(tmp_path)
    report = json.loads((tmp_path / "feedback-output/feedback-report.json").read_text())
    report["evaluation"]["findings"].append({"code": "fixture", "action": '</script><img src=x onerror=alert(1)> {{BODY}}'})
    page = render_feedback_report(report)
    assert '<img src=x' not in page
    assert '&lt;img src=x' in page
    assert '{{BODY}}' in page
