import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.server import scheduler


class SchedulerTests(unittest.TestCase):
    def test_reminders_are_ordered_by_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "reminders.db"
            with patch.object(scheduler, "DB", db):
                scheduler.init_db()
                scheduler.remind_add("later", "2026-06-28T20:00:00")
                scheduler.remind_add("earlier", "2026-06-28T18:00:00")

                rows = scheduler.reminders_list()

        self.assertEqual([row["text"] for row in rows], ["later", "earlier"])
        self.assertEqual([row["id"] for row in rows], [1, 2])


if __name__ == "__main__":
    unittest.main()
