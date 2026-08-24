from __future__ import annotations

import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import extraction_roles, profile_experiences  # noqa: E402
from app.schemas.resume import Experience, Profile, ProfileInfo, ResumeData  # noqa: E402
from app.services.experience_service import JobSelection, _role_payload  # noqa: E402
from app.services.tailored_resume_service import build_tailored_data  # noqa: E402


class CompanySummaryTests(unittest.TestCase):
    def test_resume_schema_defaults_legacy_payload_to_empty(self) -> None:
        experience = Experience(id="legacy", company="Legacy Co")
        self.assertEqual(experience.companySummary, "")
        self.assertEqual(
            Experience(**experience.model_dump()).companySummary,
            "",
        )

    def test_profile_table_has_non_null_company_summary_column(self) -> None:
        for table in (profile_experiences, extraction_roles):
            with self.subTest(table=table.name):
                column = table.c.company_summary
                self.assertFalse(column.nullable)
                self.assertIsNotNone(column.server_default)

    def test_extraction_role_payload_carries_company_summary(self) -> None:
        payload = _role_payload(
            "Job 1",
            JobSelection(
                company="Known Co",
                product="Platform",
                company_summary="Infrastructure products for logistics teams.",
            ),
        )
        self.assertEqual(
            payload["companySummary"],
            "Infrastructure products for logistics teams.",
        )

    def test_tailored_roles_copy_summary_or_default_empty(self) -> None:
        profile = Profile(
            id="00000000-0000-0000-0000-000000000001",
            name="Test",
            data=ResumeData(
                profile=ProfileInfo(professionalTitle="Engineer"),
                experience=[],
            ),
        )
        extracted = {
            "job2": {
                "company": "Recent Co",
                "timeline": "2022 - Present",
                "summary": "Built the company's platform.",
                "bullets": ["Improved reliability."],
            },
            "job1": {
                "company": "Earlier Co",
                "timeline": "2019 - 2022",
                "bullets": ["Reduced latency."],
            },
        }

        data = build_tailored_data(profile, extracted)
        self.assertEqual(data.experience[0].companySummary, "Built the company's platform.")
        self.assertEqual(data.experience[1].companySummary, "")

    def test_tailored_role_reuses_matching_profile_company_summary(self) -> None:
        profile = Profile(
            id="00000000-0000-0000-0000-000000000001",
            name="Test",
            data=ResumeData(
                profile=ProfileInfo(professionalTitle="Engineer"),
                experience=[
                    Experience(
                        id="profile-role",
                        company="Known Co",
                        title="Staff Engineer",
                        location="Chicago, IL",
                        companySummary="Infrastructure products for logistics teams.",
                    )
                ],
            ),
        )
        extracted = {
            "job2": {
                "company": "known co",
                "timeline": "2022 - Present",
                "bullets": ["Improved reliability."],
            }
        }

        data = build_tailored_data(profile, extracted)
        self.assertEqual(
            data.experience[0].companySummary,
            "Infrastructure products for logistics teams.",
        )


if __name__ == "__main__":
    unittest.main()
