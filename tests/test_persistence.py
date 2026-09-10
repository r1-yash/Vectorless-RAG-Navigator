"""Unit tests for SQLite database persistence, status management, and server restart simulation."""

import os
import tempfile
import unittest
from pathlib import Path

from src import config
from src.models import LeafSpan, SubsectionNode, SectionNode, TopicTree


class TestSQLitePersistence(unittest.TestCase):

    def setUp(self):
        # Create a temporary SQLite database file for testing isolated from production data
        self.temp_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db_file.close()
        
        # Override config DATABASE_PATH and DATABASE_URL
        self.original_db_path = config.DATABASE_PATH
        self.original_db_url = config.DATABASE_URL
        
        config.DATABASE_PATH = Path(self.temp_db_file.name)
        config.DATABASE_URL = f"sqlite:///{config.DATABASE_PATH.resolve()}"

        # Re-import db and storage modules to bind to temporary database
        import src.db as db
        import src.services.storage as storage
        
        db.engine.dispose()
        db.engine = db.create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})
        db.SessionLocal.configure(bind=db.engine)
        db.init_db()

        self.db = db
        self.storage = storage

    def tearDown(self):
        self.db.engine.dispose()
        if os.path.exists(self.temp_db_file.name):
            os.remove(self.temp_db_file.name)
        config.DATABASE_PATH = self.original_db_path
        config.DATABASE_URL = self.original_db_url

    def test_save_and_load_tree_sqlite(self):
        leaf1 = LeafSpan(span_id="sec_1_sub_1_leaf_0", start_ts=0.0, end_ts=15.0, text="First leaf transcript content.")
        leaf2 = LeafSpan(span_id="sec_1_sub_1_leaf_1", start_ts=15.0, end_ts=30.0, text="Second leaf transcript content.")
        
        sub1 = SubsectionNode(
            id="sec_1_sub_1",
            title="Subsection One",
            summary="Subsection one summary.",
            start_ts=0.0,
            end_ts=30.0,
            leaves=[leaf1, leaf2],
        )
        sec1 = SectionNode(
            id="sec_1",
            title="Section One",
            summary="Section one summary.",
            start_ts=0.0,
            end_ts=30.0,
            subsections=[sub1],
        )
        tree = TopicTree(
            video_id="test_vid_123",
            title="Test Persistence Video",
            duration=30.0,
            sections=[sec1],
        )

        # Save to SQLite
        self.storage.save_tree(tree)

        # Verify DB status
        self.assertTrue(self.storage.has_tree("test_vid_123"))
        self.assertEqual(self.storage.get_video_status("test_vid_123"), "ready")

        # Load tree from SQLite
        loaded_tree = self.storage.load_tree("test_vid_123")
        self.assertIsNotNone(loaded_tree)
        self.assertEqual(loaded_tree.video_id, "test_vid_123")
        self.assertEqual(loaded_tree.title, "Test Persistence Video")
        self.assertEqual(len(loaded_tree.sections), 1)
        self.assertEqual(loaded_tree.sections[0].title, "Section One")
        self.assertEqual(len(loaded_tree.sections[0].subsections), 1)
        self.assertEqual(len(loaded_tree.sections[0].subsections[0].leaves), 2)
        self.assertEqual(loaded_tree.sections[0].subsections[0].leaves[0].text, "First leaf transcript content.")

    def test_status_transitions_processing_and_failure(self):
        video_id = "test_vid_status"

        # Initially no status
        self.assertIsNone(self.storage.get_video_status(video_id))
        self.assertFalse(self.storage.has_tree(video_id))

        # Mark processing
        self.storage.mark_video_processing(video_id)
        self.assertEqual(self.storage.get_video_status(video_id), "processing")
        self.assertFalse(self.storage.has_tree(video_id))  # Not ready yet

        # Mark failed
        self.storage.mark_video_failed(video_id)
        self.assertEqual(self.storage.get_video_status(video_id), "failed")
        self.assertFalse(self.storage.has_tree(video_id))

    def test_simulated_server_restart(self):
        """Verify server restart persistence by closing DB connections and reloading tree from disk."""
        leaf = LeafSpan(span_id="sec_1_sub_1_leaf_0", start_ts=0.0, end_ts=10.0, text="Restart persistence text.")
        sub = SubsectionNode(id="sec_1_sub_1", title="Sub", summary="Sub sum", start_ts=0.0, end_ts=10.0, leaves=[leaf])
        sec = SectionNode(id="sec_1", title="Sec", summary="Sec sum", start_ts=0.0, end_ts=10.0, subsections=[sub])
        tree = TopicTree(video_id="restart_vid", title="Server Restart Video", duration=10.0, sections=[sec])

        # Save tree to SQLite database
        self.storage.save_tree(tree)

        # Simulate complete server restart: dispose current DB engine and connections
        self.db.engine.dispose()

        # Re-initialize DB engine simulating app process restart
        self.db.engine = self.db.create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})
        self.db.SessionLocal.configure(bind=self.db.engine)

        # Confirm data persists intact and is queryable without re-ingestion
        reloaded_tree = self.storage.load_tree("restart_vid")
        self.assertIsNotNone(reloaded_tree)
        self.assertEqual(reloaded_tree.title, "Server Restart Video")
        self.assertEqual(reloaded_tree.sections[0].subsections[0].leaves[0].text, "Restart persistence text.")


if __name__ == "__main__":
    unittest.main()
