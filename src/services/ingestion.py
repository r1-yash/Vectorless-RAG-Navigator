"""Tree construction service for converting raw transcript blocks into hierarchical topic trees."""

import time
from typing import List
from datetime import datetime, timezone

from src import config
from src.models import (
    TopicTree,
    SectionNode,
    SubsectionNode,
    LeafSpan,
    TranscriptChunk,
    SegmentationResult,
    NodeSummaryResult,
)
from src.services.youtube import fetch_raw_transcript, stitch_chunks_into_blocks, fetch_video_metadata
from src.services.llm_client import LLMClient


def build_topic_tree_for_video(video_id: str, video_title: str = "") -> TopicTree:
    """
    Ingest a YouTube video, segment its transcript into a 2-level topic tree,
    generate node summaries, and persist leaf timestamp spans.
    """
    meta = fetch_video_metadata(video_id)
    final_title = video_title or meta.get("title", f"Lecture ({video_id})")

    raw_chunks = fetch_raw_transcript(video_id)
    total_duration = raw_chunks[-1].end_ts if raw_chunks else 0.0

    # Stitch raw micro-chunks into ~150 word blocks for fine-grained topic tree segmentation
    blocks = stitch_chunks_into_blocks(raw_chunks, target_words_per_block=150)
    num_blocks = len(blocks)

    llm = LLMClient()

    # Step 1: LLM-based Topic Segmentation
    segmentation = _segment_transcript_blocks(llm, blocks, final_title)

    # Step 2: Build 2-level hierarchy & generate node summaries
    sections: List[SectionNode] = []
    sec_counter = 1
    num_sections = max(1, len(segmentation.sections))

    for sec_idx, sec_spec in enumerate(segmentation.sections):
        sec_id = f"sec_{sec_counter}"
        sec_subsections: List[SubsectionNode] = []
        sub_counter = 1

        # Fallback if LLM provided no subsections for this section
        sub_specs = sec_spec.subsections
        if not sub_specs:
            start_fallback = int((sec_idx / num_sections) * num_blocks)
            end_fallback = int(((sec_idx + 1) / num_sections) * num_blocks) - 1
            start_fallback = max(0, min(start_fallback, num_blocks - 1))
            end_fallback = max(start_fallback, min(end_fallback, num_blocks - 1))
            
            sub_specs = [
                SegmentationSubsection(
                    title=f"{sec_spec.title} Overview",
                    summary_hint=sec_spec.summary_hint or sec_spec.title,
                    block_start_index=start_fallback,
                    block_end_index=end_fallback,
                )
            ]

        for sub_spec in sub_specs:
            sub_id = f"{sec_id}_sub_{sub_counter}"
            
            start_b = max(0, min(sub_spec.block_start_index, num_blocks - 1))
            end_b = max(start_b, min(sub_spec.block_end_index, num_blocks - 1))

            sub_blocks = blocks[start_b : end_b + 1]
            if not sub_blocks:
                fallback_b = max(0, min(sec_idx, num_blocks - 1))
                sub_blocks = [blocks[fallback_b]]

            sub_start_ts = sub_blocks[0].start_ts
            sub_end_ts = sub_blocks[-1].end_ts

            leaves = [
                LeafSpan(
                    span_id=f"{sub_id}_leaf_{b_i}",
                    start_ts=b.start_ts,
                    end_ts=b.end_ts,
                    text=b.text,
                )
                for b_i, b in enumerate(sub_blocks)
            ]

            sub_text_combined = " ".join([l.text for l in leaves])
            sub_summary = _generate_node_summary(llm, sub_spec.title, sub_text_combined)

            sec_subsections.append(
                SubsectionNode(
                    id=sub_id,
                    title=sub_spec.title,
                    summary=sub_summary,
                    start_ts=sub_start_ts,
                    end_ts=sub_end_ts,
                    leaves=leaves,
                )
            )
            sub_counter += 1
            time.sleep(config.BATCH_INGESTION_DELAY_SECONDS)

        sec_start_ts = sec_subsections[0].start_ts if sec_subsections else 0.0
        sec_end_ts = sec_subsections[-1].end_ts if sec_subsections else 0.0

        all_sec_sub_summaries = " ".join([s.summary for s in sec_subsections])
        sec_summary = _generate_node_summary(llm, sec_spec.title, all_sec_sub_summaries)

        sections.append(
            SectionNode(
                id=sec_id,
                title=sec_spec.title,
                summary=sec_summary,
                start_ts=sec_start_ts,
                end_ts=sec_end_ts,
                subsections=sec_subsections,
            )
        )
        sec_counter += 1

    return TopicTree(
        video_id=video_id,
        title=final_title,
        duration=total_duration,
        sections=sections,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _segment_transcript_blocks(
    llm: LLMClient, blocks: List[TranscriptChunk], video_title: str
) -> SegmentationResult:
    """Pass block headers to LLM to create 3-8 sections with sub-sections."""
    block_descriptions = []
    for idx, block in enumerate(blocks):
        snippet = block.text[:120] + "..." if len(block.text) > 120 else block.text
        block_descriptions.append(f"Block [{idx}] ({block.start_ts:.0f}s-{block.end_ts:.0f}s): {snippet}")

    blocks_overview = "\n".join(block_descriptions)

    system_prompt = (
        "You are an expert academic lecture editor. Your job is to divide a video transcript into a 2-level "
        "hierarchical topic tree (Sections and Subsections). Every block index from 0 to N-1 must be assigned "
        "sequentially without gaps."
    )
    user_prompt = (
        f"Video Title: {video_title}\n"
        f"Total Blocks: {len(blocks)}\n\n"
        f"Transcript Block Summaries:\n{blocks_overview}\n\n"
        f"Segment the lecture into 3 to 7 main Sections. For each Section, split it into 1 to 4 Subsections. "
        f"Ensure block index ranges strictly match 0 to {len(blocks) - 1} sequentially."
    )

    return llm.call_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=SegmentationResult,
        temperature=0.1,
    )


def _generate_node_summary(llm: LLMClient, title: str, text: str) -> str:
    """Generate concise 2-3 sentence summary for tree nodes to keep query-time prompts small."""
    system_prompt = "You are a concise academic summarizer. Summarize content into 2-3 clear sentences."
    user_prompt = f"Topic Title: {title}\n\nContent:\n{text[:3000]}\n\nProvide a 2-3 sentence summary."
    result = llm.call_structured(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_model=NodeSummaryResult,
        temperature=0.2,
    )
    return result.summary
