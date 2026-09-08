"""SQLite database persistence repository for topic trees and video processing states."""

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session

import json
from src.db import SessionLocal, VideoModel, TreeNodeModel, QueryHistoryModel, init_db
from src.models import (
    TopicTree,
    SectionNode,
    SubsectionNode,
    LeafSpan,
    SampleVideo,
    VideoItem,
    QueryHistoryItem,
    TimestampMarker,
)
from src.services.youtube import fetch_video_metadata


def save_tree(tree: TopicTree) -> None:
    """Persist a TopicTree to SQLite database as structured section, subsection, and leaf nodes."""
    init_db()  # Ensure tables exist before writing
    session: Session = SessionLocal()
    try:
        # Fetch thumbnail & channel metadata
        meta = fetch_video_metadata(tree.video_id)

        # Build combined high-level video summary for multi-video routing
        sec_summaries = [f"• {sec.title}: {sec.summary}" for sec in tree.sections]
        combined_summary = f"{tree.title}\n" + "\n".join(sec_summaries)

        video = session.query(VideoModel).filter_by(video_id=tree.video_id).first()
        if not video:
            video = VideoModel(video_id=tree.video_id)
            session.add(video)

        video.title = tree.title or meta["title"]
        video.channel_name = meta.get("channel", "YouTube Channel")
        video.thumbnail_url = meta.get("thumbnail_url", f"https://img.youtube.com/vi/{tree.video_id}/hqdefault.jpg")
        video.url = f"https://www.youtube.com/watch?v={tree.video_id}"
        video.duration = tree.duration
        video.processed_at = datetime.now(timezone.utc)
        video.status = "ready"
        video.video_summary = combined_summary

        # Wipe existing tree nodes to support clean overwrite/re-ingestion
        session.query(TreeNodeModel).filter_by(video_id=tree.video_id).delete()

        sort_index = 0
        for sec in tree.sections:
            sec_node = TreeNodeModel(
                video_id=tree.video_id,
                node_id=sec.id,
                parent_node_id=None,
                level="section",
                title=sec.title,
                summary=sec.summary,
                start_ts=sec.start_ts,
                end_ts=sec.end_ts,
                raw_text=None,
                sort_order=sort_index,
            )
            session.add(sec_node)
            sort_index += 1

            for sub in sec.subsections:
                sub_node = TreeNodeModel(
                    video_id=tree.video_id,
                    node_id=sub.id,
                    parent_node_id=sec.id,
                    level="subsection",
                    title=sub.title,
                    summary=sub.summary,
                    start_ts=sub.start_ts,
                    end_ts=sub.end_ts,
                    raw_text=None,
                    sort_order=sort_index,
                )
                session.add(sub_node)
                sort_index += 1

                for leaf in sub.leaves:
                    leaf_node = TreeNodeModel(
                        video_id=tree.video_id,
                        node_id=leaf.span_id,
                        parent_node_id=sub.id,
                        level="leaf",
                        title=None,
                        summary=None,
                        start_ts=leaf.start_ts,
                        end_ts=leaf.end_ts,
                        raw_text=leaf.text,
                        sort_order=sort_index,
                    )
                    session.add(leaf_node)
                    sort_index += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def load_tree(video_id: str) -> Optional[TopicTree]:
    """Retrieve and reconstruct a nested TopicTree domain object from SQLite records."""
    init_db()
    session: Session = SessionLocal()
    try:
        video = session.query(VideoModel).filter_by(video_id=video_id, status="ready").first()
        if not video:
            return None

        db_nodes = (
            session.query(TreeNodeModel)
            .filter_by(video_id=video_id)
            .order_by(TreeNodeModel.sort_order.asc())
            .all()
        )

        sections_dict = {}
        subsections_dict = {}

        for node in db_nodes:
            if node.level == "section":
                sections_dict[node.node_id] = SectionNode(
                    id=node.node_id,
                    title=node.title or "",
                    summary=node.summary or "",
                    start_ts=node.start_ts,
                    end_ts=node.end_ts or 0.0,
                    subsections=[],
                )
            elif node.level == "subsection":
                subsections_dict[node.node_id] = {
                    "model": SubsectionNode(
                        id=node.node_id,
                        title=node.title or "",
                        summary=node.summary or "",
                        start_ts=node.start_ts,
                        end_ts=node.end_ts or 0.0,
                        leaves=[],
                    ),
                    "parent_id": node.parent_node_id,
                }

        for node in db_nodes:
            if node.level == "leaf":
                leaf = LeafSpan(
                    span_id=node.node_id,
                    start_ts=node.start_ts,
                    end_ts=node.end_ts or node.start_ts,
                    text=node.raw_text or "",
                )
                if node.parent_node_id in subsections_dict:
                    subsections_dict[node.parent_node_id]["model"].leaves.append(leaf)

        for sub_id, sub_info in subsections_dict.items():
            parent_sec_id = sub_info["parent_id"]
            if parent_sec_id in sections_dict:
                sections_dict[parent_sec_id].subsections.append(sub_info["model"])

        return TopicTree(
            video_id=video.video_id,
            title=video.title,
            duration=video.duration,
            sections=list(sections_dict.values()),
            created_at=video.processed_at.isoformat() if video.processed_at else None,
        )
    finally:
        session.close()


def list_ingested_videos() -> List[VideoItem]:
    """Retrieve all ready ingested videos from SQLite database."""
    init_db()
    session: Session = SessionLocal()
    try:
        videos = (
            session.query(VideoModel)
            .filter_by(status="ready")
            .order_by(VideoModel.processed_at.desc())
            .all()
        )
        items = []
        for v in videos:
            sec_count = (
                session.query(TreeNodeModel)
                .filter_by(video_id=v.video_id, level="section")
                .count()
            )
            items.append(
                VideoItem(
                    video_id=v.video_id,
                    title=v.title or f"Lecture ({v.video_id})",
                    channel=v.channel_name or "YouTube Lecture",
                    duration=v.duration or 0.0,
                    thumbnail_url=v.thumbnail_url or f"https://img.youtube.com/vi/{v.video_id}/hqdefault.jpg",
                    processed_at=v.processed_at.isoformat() if v.processed_at else None,
                    status=v.status,
                    summary=v.video_summary or "",
                    section_count=sec_count,
                )
            )
        return items
    finally:
        session.close()


def delete_video(video_id: str) -> bool:
    """Delete video and all cascading tree nodes & query history from SQLite."""
    init_db()
    session: Session = SessionLocal()
    try:
        video = session.query(VideoModel).filter_by(video_id=video_id).first()
        if not video:
            return False
        session.delete(video)
        session.query(QueryHistoryModel).filter_by(video_id=video_id).delete()
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def save_query_history(
    video_id: str,
    question: str,
    answer: str,
    selected_nodes: List[str],
    rationale: str,
    timestamps: List[TimestampMarker],
) -> None:
    """Save a Q&A interaction into SQLite query_history table."""
    init_db()
    session: Session = SessionLocal()
    try:
        ts_dicts = [ts.model_dump() for ts in timestamps]
        record = QueryHistoryModel(
            video_id=video_id,
            question=question,
            answer=answer,
            selected_nodes=json.dumps(selected_nodes),
            rationale=rationale,
            timestamps_json=json.dumps(ts_dicts),
        )
        session.add(record)
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def get_query_history(video_id: Optional[str] = None) -> List[QueryHistoryItem]:
    """Fetch stored Q&A interactions for a given video_id or all videos."""
    init_db()
    session: Session = SessionLocal()
    try:
        query = session.query(QueryHistoryModel)
        if video_id and video_id != "all":
            query = query.filter_by(video_id=video_id)
        records = query.order_by(QueryHistoryModel.created_at.asc()).all()

        items = []
        for r in records:
            try:
                nodes = json.loads(r.selected_nodes)
            except Exception:
                nodes = []
            try:
                ts_raw = json.loads(r.timestamps_json)
                ts_objs = [TimestampMarker(**ts) for ts in ts_raw]
            except Exception:
                ts_objs = []

            items.append(
                QueryHistoryItem(
                    id=r.id,
                    video_id=r.video_id,
                    question=r.question,
                    answer=r.answer,
                    selected_nodes=nodes,
                    rationale=r.rationale,
                    timestamps=ts_objs,
                    created_at=r.created_at.isoformat() if r.created_at else "",
                )
            )
        return items
    finally:
        session.close()


def clear_query_history(video_id: Optional[str] = None) -> None:
    """Clear chat history for a video or all videos."""
    init_db()
    session: Session = SessionLocal()
    try:
        query = session.query(QueryHistoryModel)
        if video_id and video_id != "all":
            query = query.filter_by(video_id=video_id)
        query.delete()
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def has_tree(video_id: str) -> bool:
    """Check if a video tree has already been fully ingested and stored in SQLite database."""
    init_db()
    session: Session = SessionLocal()
    try:
        video = session.query(VideoModel).filter_by(video_id=video_id, status="ready").first()
        return video is not None
    finally:
        session.close()


def get_video_status(video_id: str) -> Optional[str]:
    """Fetch current status (processing, ready, failed) for a given video_id."""
    init_db()
    session: Session = SessionLocal()
    try:
        video = session.query(VideoModel).filter_by(video_id=video_id).first()
        return video.status if video else None
    finally:
        session.close()


def mark_video_processing(video_id: str, url: str = "") -> None:
    """Record an ingestion attempt in status='processing' to block concurrent duplicate runs."""
    init_db()
    session: Session = SessionLocal()
    try:
        video = session.query(VideoModel).filter_by(video_id=video_id).first()
        if not video:
            video = VideoModel(
                video_id=video_id,
                url=url or f"https://www.youtube.com/watch?v={video_id}",
                status="processing",
            )
            session.add(video)
        else:
            video.status = "processing"
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def mark_video_failed(video_id: str) -> None:
    """Flag video status as failed following an unrecoverable ingestion exception."""
    init_db()
    session: Session = SessionLocal()
    try:
        video = session.query(VideoModel).filter_by(video_id=video_id).first()
        if video:
            video.status = "failed"
            session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def list_sample_videos() -> List[SampleVideo]:
    """Return ingested videos formatted as sample video objects if any exist."""
    ingested = list_ingested_videos()
    samples = []
    for item in ingested:
        samples.append(
            SampleVideo(
                video_id=item.video_id,
                title=item.title,
                channel=item.channel,
                duration=item.duration,
                thumbnail_url=item.thumbnail_url,
                description=item.summary or "Ingested Lecture",
                sample_questions=["What is the main topic of this lecture?", "Summarize the key sections."],
            )
        )
    return samples
