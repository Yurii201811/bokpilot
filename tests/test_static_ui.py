import unittest
from html.parser import HTMLParser
from importlib.resources import files


class UiParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.labels = set()
        self.controls = []
        self.h1 = 0
        self.skip_links = 0
        self.alerts = 0
        self.statuses = 0
        self.table_row_tabindex = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"])
        if tag == "label" and values.get("for"):
            self.labels.add(values["for"])
        if tag in {"input", "select", "textarea"} and values.get("type") != "hidden":
            self.controls.append((values.get("id"), values.get("aria-label")))
        if tag == "h1":
            self.h1 += 1
        if tag == "a" and values.get("href") == "#main-content":
            self.skip_links += 1
        if values.get("role") == "alert":
            self.alerts += 1
        if values.get("role") == "status":
            self.statuses += 1
        if tag == "tr" and "tabindex" in values:
            self.table_row_tabindex.append(values["tabindex"])


class StaticUiTest(unittest.TestCase):
    def setUp(self):
        parser = UiParser()
        parser.feed(files("bokpilot").joinpath("resources", "static", "index.html").read_text())
        self.parser = parser

    def test_ids_are_unique_and_controls_are_labelled(self):
        self.assertEqual(len(self.parser.ids), len(set(self.parser.ids)))
        for identifier, aria_label in self.parser.controls:
            self.assertTrue(aria_label or identifier in self.parser.labels, identifier)

    def test_landmarks_and_status_regions_exist(self):
        self.assertEqual(self.parser.h1, 1)
        self.assertEqual(self.parser.skip_links, 1)
        self.assertGreaterEqual(self.parser.alerts, 1)
        self.assertGreaterEqual(self.parser.statuses, 1)
        self.assertEqual(self.parser.table_row_tabindex, [])


if __name__ == "__main__":
    unittest.main()
