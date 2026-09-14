from typing import Any, List, Optional
from packages.reactive_resume.models import JsonPatchOperation


class ResumePatchBuilder:
    """Builds the JSON Patch that tailors a duplicated CV.

    Every operation is "add", not "replace". RFC 6902 says replace fails when the
    target member does not exist, and a CV section such as an entry summary is
    routinely absent. Add upserts: it replaces an existing member and creates a
    missing one, which is what tailoring means in both cases.
    """

    def __init__(self):
        self.operations: List[JsonPatchOperation] = []

    def replace_headline(self, new_headline: str) -> "ResumePatchBuilder":
        self.operations.append(
            JsonPatchOperation(op="add", path="/basics/headline", value=new_headline)
        )
        return self

    def replace_summary(self, new_summary_html_or_text: str) -> "ResumePatchBuilder":
        self.operations.append(
            JsonPatchOperation(
                op="add", path="/sections/summary/content", value=new_summary_html_or_text
            )
        )
        return self

    def update_work_item_summary(self, index: int, summary_html: str) -> "ResumePatchBuilder":
        self.operations.append(
            JsonPatchOperation(
                op="add", path=f"/sections/experience/items/{index}/summary", value=summary_html
            )
        )
        return self

    def update_skills(self, skills_items: List[dict]) -> "ResumePatchBuilder":
        self.operations.append(
            JsonPatchOperation(op="add", path="/sections/skills/items", value=skills_items)
        )
        return self

    def reorder_work_items(self, reordered_items: List[dict]) -> "ResumePatchBuilder":
        self.operations.append(
            JsonPatchOperation(op="add", path="/sections/experience/items", value=reordered_items)
        )
        return self

    def add_operation(
        self, op: str, path: str, value: Optional[Any] = None, from_: Optional[str] = None
    ) -> "ResumePatchBuilder":
        self.operations.append(JsonPatchOperation(op=op, path=path, value=value, from_=from_))
        return self

    def build(self) -> List[JsonPatchOperation]:
        return self.operations
