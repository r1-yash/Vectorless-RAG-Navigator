"""Unit tests for Vectorless RAG Lecture Navigator data models and transcript stitching."""

import unittest
from src.models import (
    TranscriptChunk,
    LeafSpan,
    SubsectionNode,
    SectionNode,
    TopicTree,
    BranchSelectionResult,
    AnswerSynthesisResult,
    TimestampMarker,
)
from src.services.youtube import extract_video_id, stitch_chunks_into_blocks


class TestYouTubeService(unittest.TestCase):

    def test_extract_video_id_valid_urls(self):
        urls = [
            ("https://www.youtube.com/watch?v=zjkBMFhNj_g", "zjkBMFhNj_g"),
            ("https://youtu.be/zjkBMFhNj_g?t=10", "zjkBMFhNj_g"),
            ("https://www.youtube.com/embed/zjkBMFhNj_g", "zjkBMFhNj_g"),
            ("zjkBMFhNj_g", "zjkBMFhNj_g"),
        ]
        for url, expected_id in urls:
            self.assertEqual(extract_video_id(url), expected_id)

    def test_stitch_chunks_into_blocks(self):
        chunks = [
            TranscriptChunk(text="Hello world part 1.", start_ts=0.0, duration=2.0, end_ts=2.0),
            TranscriptChunk(text="This is chunk two of text.", start_ts=2.0, duration=3.0, end_ts=5.0),
            TranscriptChunk(text="Third chunk finishing up.", start_ts=5.0, duration=2.0, end_ts=7.0),
        ]
        # Target 5 words per block to force split
        blocks = stitch_chunks_into_blocks(chunks, target_words_per_block=5)
        self.assertGreater(len(blocks), 1)
        self.assertEqual(blocks[0].start_ts, 0.0)
        self.assertEqual(blocks[-1].end_ts, 7.0)


class TestDataModels(unittest.TestCase):

    def test_topic_tree_serialization(self):
        leaf = LeafSpan(span_id="sub_1_leaf_0", start_ts=0.0, end_ts=10.0, text="Intro text")
        sub = SubsectionNode(
            id="sec_1_sub_1",
            title="Subsection 1",
            summary="Sub summary",
            start_ts=0.0,
            end_ts=10.0,
            leaves=[leaf],
        )
        sec = SectionNode(
            id="sec_1",
            title="Section 1",
            summary="Section summary",
            start_ts=0.0,
            end_ts=10.0,
            subsections=[sub],
        )
        tree = TopicTree(
            video_id="test_vid",
            title="Test Lecture",
            duration=10.0,
            sections=[sec],
        )
        
        json_str = tree.model_dump_json()
        reconstructed = TopicTree.model_validate_json(json_str)
        self.assertEqual(reconstructed.video_id, "test_vid")
        self.assertEqual(len(reconstructed.sections), 1)
        self.assertEqual(reconstructed.sections[0].subsections[0].leaves[0].text, "Intro text")


if __name__ == "__main__":
    unittest.main()
