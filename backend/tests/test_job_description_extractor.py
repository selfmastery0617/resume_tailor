from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from app.services import job_store
from app.services.job_description_extractor import (
    JobDescriptionExtractor,
    NoExtractableJobs,
)


class FakeConversation:
    instances: list["FakeConversation"] = []

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.started = False
        self.closed = False
        self.__class__.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return f"# Extracted\n\n{prompt}"

    async def close(self) -> None:
        self.closed = True


class JobDescriptionExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_conversation_is_reused_and_each_description_is_saved(self) -> None:
        FakeConversation.instances.clear()
        rows = [
            {
                "id": "one",
                "title": "First role",
                "company": "A",
                "job_url": "https://example.com/one",
                "locked": False,
            },
            {
                "id": "two",
                "title": "Second role",
                "company": "B",
                "job_url": "https://example.com/two",
                "locked": False,
            },
        ]
        saved: list[tuple[str, dict[str, str]]] = []
        extractor = JobDescriptionExtractor()

        with (
            patch.object(job_store, "list_jobs", return_value=rows),
            patch.object(job_store, "update_job", side_effect=lambda job_id, value: saved.append((job_id, value))),
            patch("app.services.deepseek.DeepSeekConversation", FakeConversation),
        ):
            started = extractor.start(["two", "one"])
            self.assertEqual(started["state"], "running")
            await extractor._task

        self.assertEqual(len(FakeConversation.instances), 1)
        conversation = FakeConversation.instances[0]
        self.assertTrue(conversation.started)
        self.assertTrue(conversation.closed)
        self.assertEqual(
            conversation.prompts,
            [
                "https://example.com/two. That is job url. Extract the job description as markdown content",
                "https://example.com/one. That is job url. Extract the job description as markdown content",
            ],
        )
        self.assertEqual([job_id for job_id, _value in saved], ["two", "one"])
        self.assertTrue(all(value["description"].startswith("# Extracted") for _, value in saved))
        self.assertEqual(extractor.snapshot()["state"], "done")
        self.assertEqual(extractor.snapshot()["succeeded"], 2)

    async def test_no_session_is_created_when_selected_rows_are_ineligible(self) -> None:
        rows = [
            {"id": "empty", "job_url": "", "locked": False},
            {"id": "locked", "job_url": "https://example.com", "locked": True},
        ]
        extractor = JobDescriptionExtractor()

        with patch.object(job_store, "list_jobs", return_value=rows):
            with self.assertRaises(NoExtractableJobs):
                extractor.start(["empty", "locked"])

        self.assertIsNone(extractor._task)
        self.assertEqual(extractor.snapshot()["state"], "idle")

    async def test_cancel_finishes_current_row_and_stops_before_the_next(self) -> None:
        entered_ask = asyncio.Event()
        release_reply = asyncio.Event()

        class BlockingConversation(FakeConversation):
            async def ask(self, prompt: str) -> str:
                self.prompts.append(prompt)
                entered_ask.set()
                await release_reply.wait()
                return "# Current row completed"

        rows = [
            {"id": "one", "title": "One", "job_url": "https://example.com/1", "locked": False},
            {"id": "two", "title": "Two", "job_url": "https://example.com/2", "locked": False},
        ]
        extractor = JobDescriptionExtractor()

        with (
            patch.object(job_store, "list_jobs", return_value=rows),
            patch.object(job_store, "update_job"),
            patch("app.services.deepseek.DeepSeekConversation", BlockingConversation),
        ):
            extractor.start(["one", "two"])
            await entered_ask.wait()
            stopping = extractor.cancel()
            self.assertTrue(stopping["cancelRequested"])
            release_reply.set()
            await extractor._task

        status = extractor.snapshot()
        self.assertEqual(status["state"], "cancelled")
        self.assertEqual(status["done"], 1)
        self.assertEqual(status["succeeded"], 1)


if __name__ == "__main__":
    unittest.main()
