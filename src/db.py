"""SQLite database connection setup and SQLAlchemy ORM models."""

from datetime import datetime, timezone
from typing import Generator
from sqlalchemy import create_engine, Column, String, Float, DateTime, Text, Integer, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

from src import config

# check_same_thread=False allows FastAPI multi-threaded request execution on single SQLite file connection pool
engine = create_engine(config.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class VideoModel(Base):
    """SQLAlchemy ORM model for storing ingested YouTube video metadata and processing state."""

    __tablename__ = "videos"

    video_id = Column(String(64), primary_key=True, index=True)
    title = Column(String(255), nullable=False, default="")
    channel_name = Column(String(255), nullable=False, default="YouTube Lecture")
    thumbnail_url = Column(String(512), nullable=False, default="")
    url = Column(String(512), nullable=False, default="")
    duration = Column(Float, nullable=False, default=0.0)
    processed_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    status = Column(String(32), nullable=False, default="processing")  # processing, ready, failed

    video_summary = Column(Text, nullable=True)  # Prepared for multi-video index layer

    # Cascade delete tree nodes when video is deleted
    nodes = relationship("TreeNodeModel", back_populates="video", cascade="all, delete-orphan")


class TreeNodeModel(Base):
    """SQLAlchemy ORM model for storing 2-level topic tree nodes and leaf transcript spans."""

    __tablename__ = "tree_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String(64), ForeignKey("videos.video_id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(String(128), nullable=False, index=True)  # e.g., sec_1, sec_1_sub_1, sec_1_sub_1_leaf_0
    parent_node_id = Column(String(128), nullable=True)  # Nullable parent for hierarchy linking
    level = Column(String(32), nullable=False)  # section, subsection, leaf
    title = Column(String(255), nullable=True)
    summary = Column(Text, nullable=True)  # Section and subsection summary text
    start_ts = Column(Float, nullable=False)
    end_ts = Column(Float, nullable=True)  # Nullable for non-leaf nodes per prompt spec
    raw_text = Column(Text, nullable=True)  # Nullable raw transcript text for leaf nodes
    sort_order = Column(Integer, nullable=False, default=0)  # Preserves exact sequential ordering

    video = relationship("VideoModel", back_populates="nodes")


class QueryHistoryModel(Base):
    """SQLAlchemy ORM model for storing persistent Q&A chat history per video or multi-video session."""

    __tablename__ = "query_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(String(64), nullable=False, index=True, default="all")
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    selected_nodes = Column(Text, nullable=False, default="[]")  # JSON string array
    rationale = Column(Text, nullable=False, default="")
    timestamps_json = Column(Text, nullable=False, default="[]")  # JSON string array
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


def init_db() -> None:
    """Initialize database tables if they do not already exist and run light migrations."""
    Base.metadata.create_all(bind=engine)
    
    # Auto-add columns if migrating an existing SQLite database
    with engine.connect() as conn:
        try:
            from sqlalchemy import text
            res = conn.execute(text("PRAGMA table_info(videos)"))
            cols = [r[1] for r in res.fetchall()]
            if "channel_name" not in cols:
                conn.execute(text("ALTER TABLE videos ADD COLUMN channel_name VARCHAR(255) DEFAULT 'YouTube Lecture'"))
            if "thumbnail_url" not in cols:
                conn.execute(text("ALTER TABLE videos ADD COLUMN thumbnail_url VARCHAR(512) DEFAULT ''"))
            conn.commit()
        except Exception:
            pass


def get_db() -> Generator[Session, None, None]:
    """Dependency helper to yield database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
