"""Integration unit tests for video history, Q&A persistence, and multi-video RAG."""

import unittest
from src.db import init_db
from src.models import TopicTree, SectionNode, SubsectionNode, LeafSpan, TimestampMarker
from src.services.storage import (
    save_tree,
    list_ingested_videos,
    delete_video,
    save_query_history,
    get_query_history,
    clear_query_history,
)
from src.services.retrieval import answer_question_vectorless_multi


class TestMultiVideoAndHistory(unittest.TestCase):

    def setUp(self):
        init_db()

    def test_video_saving_and_listing(self):
        leaf1 = LeafSpan(span_id="sec1_sub1_leaf0", start_ts=0.0, end_ts=30.0, text="Intro to Machine Learning")
        sub1 = SubsectionNode(
            id="sec_1_sub_1",
            title="Overview",
            summary="Overview of ML concepts",
            start_ts=0.0,
            end_ts=30.0,
            leaves=[leaf1],
        )
        sec1 = SectionNode(
            id="sec_1",
            title="Introduction",
            summary="High level intro",
            start_ts=0.0,
            end_ts=30.0,
            subsections=[sub1],
        )
        tree1 = TopicTree(
            video_id="test_vid_111",
            title="Machine Learning 101",
            duration=30.0,
            sections=[sec1],
        )
        save_tree(tree1)

        ingested = list_ingested_videos()
        self.assertTrue(any(v.video_id == "test_vid_111" for v in ingested))

    def test_query_history_persistence(self):
        video_id = "test_vid_111"
        save_query_history(
            video_id=video_id,
            question="What is ML?",
            answer="ML is Machine Learning.",
            selected_nodes=["sec_1"],
            rationale="Selected intro section.",
            timestamps=[TimestampMarker(start_ts=0.0, label="Intro clip", video_id=video_id)],
        )

        history = get_query_history(video_id)
        self.assertGreater(len(history), 0)
        latest = history[-1]
        self.assertEqual(latest.question, "What is ML?")
        self.assertEqual(latest.answer, "ML is Machine Learning.")

        clear_query_history(video_id)
        history_after = get_query_history(video_id)
        self.assertEqual(len(history_after), 0)

    def test_delete_video(self):
        video_id = "test_vid_del"
        leaf1 = LeafSpan(span_id="del_leaf0", start_ts=0.0, end_ts=10.0, text="To be deleted")
        sub1 = SubsectionNode(id="del_sub", title="Sub", summary="Sum", start_ts=0.0, end_ts=10.0, leaves=[leaf1])
        sec1 = SectionNode(id="del_sec", title="Sec", summary="Sum", start_ts=0.0, end_ts=10.0, subsections=[sub1])
        tree = TopicTree(video_id=video_id, title="Delete Test", duration=10.0, sections=[sec1])
        save_tree(tree)

        deleted = delete_video(video_id)
        self.assertTrue(deleted)
        ingested = list_ingested_videos()
        self.assertFalse(any(v.video_id == video_id for v in ingested))


if __name__ == "__main__":
    unittest.main()
