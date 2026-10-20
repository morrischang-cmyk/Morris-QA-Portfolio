import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from jira_task_manager import (
    build_parent_fields,
    build_subtask_fields,
    build_subtask_summary,
    parse_members,
    resolve_subtask_issue_type,
)


class TaskManagerRulesTest(unittest.TestCase):
    def test_members_are_trimmed_and_deduplicated(self) -> None:
        self.assertEqual(parse_members("Morris, Amy\nMorris，Leo"), ["Morris", "Amy", "Leo"])

    def test_subtask_summary_uses_main_issue_and_member(self) -> None:
        self.assertEqual(build_subtask_summary("GAME-1234", " Morris "), "GAME-1234_Morris")

    def test_parent_payload_copies_only_selected_fields(self) -> None:
        template = {
            "fields": {
                "project": {"id": "10001", "key": "QA"},
                "issuetype": {"id": "10002", "name": "Task"},
                "description": "template description",
                "priority": {"id": "3", "name": "Medium"},
                "labels": ["qa"],
                "assignee": {"name": "old-user"},
            }
        }
        fields = build_parent_fields(template, "New QA task", ["description", "priority", "labels"])

        self.assertEqual(fields["summary"], "New QA task")
        self.assertEqual(fields["priority"], {"id": "3"})
        self.assertNotIn("assignee", fields)

    def test_existing_template_subtask_type_is_reused(self) -> None:
        template = {
            "fields": {
                "subtasks": [
                    {"fields": {"issuetype": {"id": "10004", "name": "QA Sub-task"}}}
                ]
            }
        }
        self.assertEqual(resolve_subtask_issue_type(template, "Sub-task"), {"id": "10004"})

    def test_subtask_payload_uses_created_parent_key(self) -> None:
        parent_fields = {"project": {"id": "10001"}}
        fields = build_subtask_fields(
            parent_fields,
            "QA-12000",
            "GAME-1234",
            "Morris",
            {"id": "10004"},
        )

        self.assertEqual(fields["parent"], {"key": "QA-12000"})
        self.assertEqual(fields["summary"], "GAME-1234_Morris")


if __name__ == "__main__":
    unittest.main()
