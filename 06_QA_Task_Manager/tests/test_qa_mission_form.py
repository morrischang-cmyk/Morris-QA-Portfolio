import sys
import unittest
from datetime import date
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from qa_mission_form import (
    build_create_fields,
    build_mission_data,
    description_lines,
    extract_section,
    format_jira_date,
    resolve_environment_agents,
    select_latest_release_block,
    validate_date,
)


class QaMissionFormTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = {
            "headings": {
                "test_items": "進測項目",
                "environment": "驗證環境",
                "version": "驗證版號",
            },
            "description_boundaries": ["遊戲連結", "後台連結", "代理"],
            "environment_agent_map": {"SIT": "agent-sit"},
        }

    def test_extract_test_items_until_environment(self) -> None:
        lines = ["[進測項目]", "登入", "下注流程", "驗證環境", "SIT"]
        value = extract_section(lines, "進測項目", ["驗證環境", "驗證版號"])
        self.assertEqual(value, "登入\n下注流程")

    def test_inline_bracket_sections_are_extracted_separately(self) -> None:
        lines = ["[進測項目] 登入", "下注", "[驗證環境] SIT", "[驗證版號] 1.2.3"]
        self.assertEqual(extract_section(lines, "進測項目", ["驗證環境"]), "登入\n下注")
        self.assertEqual(extract_section(lines, "驗證環境", ["驗證版號"]), "SIT")
        self.assertEqual(extract_section(lines, "驗證版號", ["進測項目"]), "1.2.3")

    def test_adf_description_is_converted_to_lines(self) -> None:
        description = {
            "type": "doc",
            "content": [
                {"type": "heading", "content": [{"type": "text", "text": "進測項目"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "會員登入"}]},
            ],
        }
        self.assertEqual(description_lines(description), ["進測項目", "會員登入"])

    def test_mission_data_uses_description_sections_and_environment_agent_map(self) -> None:
        issue = {
            "key": "GAME-1234",
            "fields": {
                "reporter": {"displayName": "Morris", "name": "morris706"},
                "description": "[進測項目]\n登入\n驗證環境\nSIT\n驗證版號\n1.2.3",
            },
        }
        result = build_mission_data(issue, "https://jira.example.com", self.rules)

        self.assertEqual(result["main_issue_url"], "https://jira.example.com/browse/GAME-1234")
        self.assertEqual(result["reporter_name"], "Morris")
        self.assertEqual(result["test_items"], "登入")
        self.assertEqual(result["environment"], "SIT")
        self.assertEqual(result["version"], "1.2.3")
        self.assertEqual(result["agent"], "agent-sit")

    def test_description_sections_take_precedence_over_same_named_jira_fields(self) -> None:
        issue = {
            "key": "GAME-1234",
            "names": {"customfield_1": "驗證環境", "customfield_2": "驗證版號"},
            "fields": {
                "reporter": {"displayName": "Morris"},
                "description": "進測項目\n登入\n驗證環境\nUAT\n驗證版號\n2.0.0",
                "customfield_1": "SIT",
                "customfield_2": "1.0.0",
            },
        }
        result = build_mission_data(issue, "https://jira.example.com", self.rules)
        self.assertEqual(result["environment"], "UAT")
        self.assertEqual(result["version"], "2.0.0")

    def test_version_stops_before_following_template_sections(self) -> None:
        issue = {
            "key": "GAME-1234",
            "fields": {
                "reporter": {"displayName": "Morris"},
                "description": "進測項目\n登入\n驗證環境\nSIT\n驗證版號\n1.2.3\n[遊戲連結] https://game.example.com",
            },
        }
        result = build_mission_data(issue, "https://jira.example.com", self.rules)
        self.assertEqual(result["version"], "1.2.3")

    def test_highest_release_block_and_version_heading_alias_are_used(self) -> None:
        self.rules["headings"]["version"] = ["驗證版號", "驗證版本"]
        self.rules["description_boundaries"].append("通知時間")
        issue = {
            "key": "HCIYL-21021",
            "fields": {
                "summary": "[YL][QA][R2] 測試",
                "reporter": {"displayName": "PM", "name": "pm-user"},
                "description": (
                    "*R2*\n"
                    "[進測項目] R2 BUG 複驗\n"
                    "[驗證環境] MERGE／YL QA\n"
                    "[驗證版本]\nClient version: newest\nServer version: newest-server\n"
                    "[通知時間] 2026/10/12\n----\n"
                    "[進測項目] 中間補測\n[驗證環境] YL QA\n"
                    "[驗證版本] Server version: middle\n----\n"
                    "[進測項目] *R1*\n舊版內容\n"
                    "[驗證環境] MERGE／YL QA\n[驗證版號] old-version"
                ),
            },
        }

        result = build_mission_data(issue, "https://jira.example.com", self.rules)

        self.assertEqual(result["test_items"], "R2 BUG 複驗")
        self.assertEqual(result["environment"], "MERGE／YL QA")
        self.assertEqual(
            result["version"], "Client version: newest\nServer version: newest-server"
        )

    def test_release_block_uses_highest_number_even_when_not_first(self) -> None:
        lines = [
            "*R2*", "[進測項目] 第二版", "----",
            "*R3*", "[進測項目] 第三版", "----",
            "[進測項目] *R1*", "第一版",
        ]
        selected = select_latest_release_block(lines, "[R2] 標題尚未更新", "進測項目")
        self.assertEqual(selected, ["*R3*", "[進測項目] 第三版"])

    def test_date_validation(self) -> None:
        self.assertEqual(validate_date("5/八月/25", "開始日期"), date(2025, 8, 5))
        self.assertEqual(format_jira_date(date(2025, 8, 5)), "5/八月/25")
        with self.assertRaises(ValueError):
            validate_date("2026-10-20", "開始日期")
        with self.assertRaises(ValueError):
            validate_date("31/二月/25", "開始日期")

    def test_multiple_environments_resolve_agents_in_source_order(self) -> None:
        agent_map = {
            "YL SIT": "[YL代理] 1(轉帳) 2(單一)",
            "V8 SIT": "[V8代理] 2(轉帳) 1(單一)",
        }
        self.assertEqual(
            resolve_environment_agents("V8-SIT  YL-SIT", agent_map),
            "[V8代理] 2(轉帳) 1(單一)\n[YL代理] 1(轉帳) 2(單一)",
        )

    def test_create_payload_uses_real_jira_fields_and_template_description(self) -> None:
        metadata = {
            "projects": [{
                "id": "10113",
                "key": "QA",
                "issuetypes": [{
                    "id": "10100",
                    "name": "Task",
                    "fields": {
                        "summary": {"name": "概要", "required": True},
                        "description": {"name": "描述", "required": True},
                        "customfield_10202": {"name": "Start date", "required": True, "schema": {"type": "date"}},
                        "duedate": {"name": "到期日", "required": True, "schema": {"type": "date"}},
                        "customfield_10109": {"name": "Epic Link", "required": False, "schema": {"type": "any"}},
                        "assignee": {"name": "經辦人", "required": False},
                        "project": {"name": "項目", "required": True},
                        "issuetype": {"name": "問題類型", "required": True},
                    },
                }],
            }],
        }
        rules = {
            "project_key": "QA",
            "issue_type": "Task",
            "assignee": "arsene211",
            "epic_link_keys": {"HCI-YL": "QA-3782"},
            "field_aliases": {
                "start_date": ["Start Date"],
                "due_date": ["到期日"],
                "epic_link": ["Epic Link"],
            },
        }
        mission = {
            "summary": "主任務摘要",
            "main_issue_key": "HCIYL-1",
            "main_issue_url": "https://jira.example.com/browse/HCIYL-1",
            "reporter_id": "morris706",
            "reporter_account_id": "",
            "test_items": "登入",
            "environment": "SIT",
            "version": "1.2.3",
            "agent": "agent-sit",
        }
        form = {
            "test_cases": "https://sheets.example.com/test",
            "start_date_api": "2026-10-19",
            "due_date_api": "2026-10-20",
            "epic_link": "HCI-YL",
        }
        fields, unresolved, missing = build_create_fields(metadata, mission, form, rules)
        self.assertEqual(fields["issuetype"], {"id": "10100"})
        self.assertEqual(fields["customfield_10202"], "2026-10-19")
        self.assertEqual(fields["duedate"], "2026-10-20")
        self.assertEqual(fields["customfield_10109"], "QA-3782")
        self.assertEqual(fields["assignee"], {"name": "arsene211"})
        self.assertIn("[測試案例]\nhttps://sheets.example.com/test", fields["description"])
        self.assertIn(
            "Bug單 block 關連到[HCIYL-1|https://jira.example.com/browse/HCIYL-1]並指派給 morris706",
            fields["description"],
        )
        self.assertIn(
            "[驗證版號] 1.2.3\n\n"
            "[遊戲連結] [https://game.example.internal/login?menuId=1]\n"
            "[後台連結] [https://qa-lab.example.internal/]\n\n"
            "agent-sit",
            fields["description"],
        )
        self.assertIn("[進測項目]\n登入\n\n[測試案例]", fields["description"])
        self.assertEqual(unresolved, [])
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
