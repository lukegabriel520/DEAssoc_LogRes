import unittest

from core.departments import Department, validate_departments
from core.sheets_store import SheetsStoreError, validate_runtime_secrets


def valid_secrets() -> dict:
    return {
        "app_password": "secret",
        "spreadsheet_id": "spreadsheet-id",
        "template_tab": "Sheet1",
        "google_service_account": {
            "type": "service_account",
            "project_id": "project",
            "private_key": "key",
            "client_email": "service@example.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    }


class ConfigurationTests(unittest.TestCase):
    def test_complete_top_level_secrets_are_accepted(self) -> None:
        validate_runtime_secrets(valid_secrets())

    def test_placeholder_spreadsheet_id_is_rejected(self) -> None:
        secrets = valid_secrets()
        secrets["spreadsheet_id"] = "YOUR_GOOGLE_SHEET_ID_HERE"

        with self.assertRaisesRegex(SheetsStoreError, "placeholder"):
            validate_runtime_secrets(secrets)

    def test_master_tab_cannot_match_department_sheet(self) -> None:
        department = Department(
            id="data",
            display_name="Data",
            sheet_name="Sheet1",
            rubric_file="data_engineering.json",
        )

        with self.assertRaisesRegex(ValueError, "conflicts"):
            validate_departments([department], master_tab_name="Sheet1")


if __name__ == "__main__":
    unittest.main()
