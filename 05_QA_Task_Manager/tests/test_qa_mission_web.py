import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from qa_mission_web import (
    HOST,
    apply_editable_values,
    build_mattermost_subtask_message,
    build_subtask_fields,
    credential_store,
    create_session,
    delete_session,
    get_lan_ip,
    load_jira_mattermost_mapping,
    normalize_estimate,
    parse_employee_mattermost_mapping,
    parse_iso_date,
    read_session,
    secure_cookie,
    tester_title_name,
    username_title_name,
    validate_selected_members,
)


class QaMissionWebTest(unittest.TestCase):
    def test_session_cookie_does_not_contain_token(self) -> None:
        session_id = create_session("morris706", "Morris", "secret-token-value")
        try:
            session = read_session(session_id)
            self.assertEqual(session["username"], "morris706")
            cookie = secure_cookie("qa_session", session_id, 3600)
            self.assertIn("HttpOnly", cookie)
            self.assertIn("SameSite=Strict", cookie)
            self.assertNotIn("secret-token-value", cookie)
        finally:
            delete_session(session_id)

    def test_server_listens_on_lan_interfaces(self) -> None:
        self.assertEqual(HOST, "0.0.0.0")
        self.assertRegex(get_lan_ip(), r"^\d{1,3}(\.\d{1,3}){3}$")

    def test_parse_browser_date(self) -> None:
        self.assertEqual(parse_iso_date("2026-10-19", "Start Date"), date(2026, 10, 19))
        with self.assertRaises(ValueError):
            parse_iso_date("", "Start Date")

    def test_apply_editable_values_uses_manual_changes(self) -> None:
        original = {"summary": "原摘要", "reporter_id": "old-user", "main_issue_key": "ABC-1"}
        payload = {
            "summary": "修改後摘要",
            "bug_assignee": "new-user",
            "qa_assignee": "qa-user",
            "test_items": "修改後進測項目",
            "environment": "UAT",
            "version": "2.0.0",
            "agent": "代理 123",
        }

        updated, qa_assignee = apply_editable_values(original, payload)

        self.assertEqual(updated["summary"], "修改後摘要")
        self.assertEqual(updated["reporter_id"], "new-user")
        self.assertEqual(updated["environment"], "UAT")
        self.assertEqual(updated["agent"], "代理 123")
        self.assertEqual(updated["main_issue_key"], "ABC-1")
        self.assertEqual(qa_assignee, "qa-user")

    def test_normalize_estimate(self) -> None:
        self.assertEqual(normalize_estimate(" 1D   2h ", "預估時間"), "1d 2h")
        with self.assertRaises(ValueError):
            normalize_estimate("四小時", "預估時間")

    def test_username_title_name_removes_trailing_digits(self) -> None:
        self.assertEqual(username_title_name("arthur734"), "arthur")
        self.assertEqual(username_title_name("ralflin460"), "ralflin")
        self.assertEqual(username_title_name("morris"), "morris")

    def test_configured_tester_title_name_overrides_account_name(self) -> None:
        testers = [{"username": "ralflin460", "title_name": "ralf"}]
        self.assertEqual(tester_title_name("ralflin460", testers), "ralf")
        self.assertEqual(tester_title_name("arthur734", testers), "arthur")

    def test_build_subtask_fields_clones_parent_and_sets_time(self) -> None:
        metadata = {
            "projects": [
                {
                    "id": "10000",
                    "key": "QA",
                    "issuetypes": [
                        {
                            "id": "10101",
                            "name": "子任务",
                            "subtask": True,
                            "fields": {
                                "summary": {"name": "概要", "required": True},
                                "description": {"name": "描述", "required": True},
                                "parent": {"name": "父版本", "required": True},
                                "project": {"name": "项目", "required": True},
                                "issuetype": {"name": "问题类型", "required": True},
                                "assignee": {"name": "经办人", "required": False},
                                "timetracking": {"name": "时间跟踪", "required": True},
                                "customfield_10202": {"name": "Start date", "required": True},
                                "customfield_10999": {"name": "Deadline", "required": False},
                                "duedate": {"name": "到期日", "required": True},
                                "priority": {"name": "优先级", "required": False},
                            },
                        }
                    ],
                }
            ]
        }
        parent = {
            "key": "QA-11097",
            "fields": {
                "project": {"key": "QA"},
                "summary": "QA 主單",
                "description": "完整測試內容",
                "customfield_10202": "2026-10-20",
                "duedate": "2026-10-25",
                "priority": {"id": "3", "name": "Medium"},
            },
        }
        payload = {
            "member_name": "Morris",
            "assignee": "morris706",
            "original_estimate": "4h",
            "remaining_estimate": "3h",
            "deadline": "2026-10-22",
        }

        fields = build_subtask_fields(metadata, parent, payload)

        self.assertEqual(fields["summary"], "QA 主單_Morris")
        self.assertEqual(fields["parent"], {"key": "QA-11097"})
        self.assertEqual(fields["assignee"], {"name": "morris706"})
        self.assertEqual(fields["timetracking"]["originalEstimate"], "4h")
        self.assertEqual(fields["timetracking"]["remainingEstimate"], "3h")
        self.assertEqual(fields["customfield_10202"], "2026-10-20")
        self.assertEqual(fields["customfield_10999"], "2026-10-22")
        self.assertEqual(fields["duedate"], "2026-10-25")

    def test_validate_multiple_selected_members(self) -> None:
        testers = [
            {"username": "arthur734"},
            {"username": "morris706"},
        ]

        selected = validate_selected_members(
            ["arthur734", "morris706", "arthur734"], testers
        )

        self.assertEqual(selected, ["arthur734", "morris706"])
        with self.assertRaises(ValueError):
            validate_selected_members(["unknown"], testers)

    def test_mattermost_message_uses_configured_mentions(self) -> None:
        mapping = {
            "lily265": {"name": "lily", "user_id": "u1"},
            "morris706": {"name": "morris", "user_id": "u2"},
        }
        message, deadline = build_mattermost_subtask_message(
            "QA-11112",
            "[V8][QA][R1] 遊戲前端引擎轉移COCOS",
            "https://jira.example.internal/browse/QA-11112",
            ["lily265", "morris706"],
            mapping,
            date(2026, 10, 22),
        )
        self.assertEqual(deadline, date(2026, 10, 22))
        self.assertIn("@lily @morris", message)
        self.assertIn("QA-11112", message)
        self.assertIn("10/22下班前完成", message)

    def test_employee_data_mapping_uses_redis_jira_and_mm_fields(self) -> None:
        pairs = [
            "ralf",
            '{"jira":"ralflin460","mm":{"name":"@ralflin","user_id":"u-ralf"}}',
            "broken",
            "not-json",
        ]
        mapping = parse_employee_mattermost_mapping(pairs)
        self.assertEqual(mapping["ralflin460"]["name"], "ralflin")
        self.assertEqual(mapping["ralflin460"]["user_id"], "u-ralf")

    @patch.object(credential_store, "read", return_value=None)
    def test_bundled_mapping_is_used_without_redis(self, _) -> None:
        mapping = load_jira_mattermost_mapping()
        self.assertEqual(mapping["morris706"]["name"], "morrischang")
        self.assertEqual(mapping["ralflin460"]["name"], "ralflin")
        self.assertEqual(mapping["leo296"]["name"], "qa_lin")
        self.assertEqual(mapping["lydia736"]["name"], "lydia")


if __name__ == "__main__":
    unittest.main()
