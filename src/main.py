"""FastAPI web application entry point for Vectorless RAG Lecture Navigator."""

import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.db import init_db
from src.models import (
    IngestRequest,
    IngestResponse,
    BatchIngestRequest,
    BatchIngestResponse,
    QueryRequest,
    QueryResponse,
    TopicTree,
    VideoItem,
    QueryHistoryItem,
)
from src.services.youtube import extract_video_id, fetch_video_metadata, YouTubeServiceError
from src.services.ingestion import build_topic_tree_for_video
from src.services.retrieval import (
    answer_question_vectorless,
    answer_question_vectorless_multi,
    RetrievalServiceError,
)
from src.services.storage import (
    save_tree,
    load_tree,
    has_tree,
    get_video_status,
    mark_video_processing,
    mark_video_failed,
    list_ingested_videos,
    delete_video,
    save_query_history,
    get_query_history,
    clear_query_history,
    list_sample_videos,
)
from src.services.llm_client import LLMClientError

app = FastAPI(
    title="Vectorless RAG Lecture Navigator",
    description="Hierarchical topic-tree LLM reasoning retrieval over YouTube lectures",
    version="0.2.0",
)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.on_event("startup")
def on_startup():
    """Ensure SQLite tables exist when application server starts up."""
    init_db()


@app.get("/api/samples")
def get_sample_videos():
    """Return pre-configured sample videos list."""
    return list_sample_videos()


@app.get("/api/videos", response_model=List[VideoItem])
def get_ingested_videos():
    """Return list of all ready ingested lectures from SQLite database."""
    return list_ingested_videos()


@app.delete("/api/videos/{video_id}")
def remove_video(video_id: str):
    """Delete an ingested lecture and its associated tree and chat history."""
    deleted = delete_video(video_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Video '{video_id}' not found.")
    return {"message": f"Successfully deleted video '{video_id}'"}


@app.post("/api/ingest", response_model=IngestResponse)
def ingest_video(req: IngestRequest):
    """
    Ingest single or multiple YouTube URLs (comma/newline separated).
    Fetch transcript, segment into a 2-level topic tree, and persist to SQLite.
    """
    raw_input = req.url.strip()
    
    # Check if multiple URLs were provided in single string
    delimiters = [",", "\n", " "]
    urls = [raw_input]
    for d in delimiters:
        if d in raw_input:
            candidate_parts = [p.strip() for p in raw_input.replace("\n", ",").split(",") if p.strip()]
            if len(candidate_parts) > 1:
                urls = candidate_parts
                break

    target_url = urls[0]

    try:
        video_id = extract_video_id(target_url)
    except YouTubeServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    meta = fetch_video_metadata(video_id)

    # Fast path: return existing tree from SQLite DB if video is already ready
    existing_status = get_video_status(video_id)
    if existing_status == "ready":
        existing = load_tree(video_id)
        if existing:
            return IngestResponse(
                video_id=video_id,
                title=existing.title,
                duration=existing.duration,
                section_count=len(existing.sections),
                status="ready",
                channel=meta.get("channel", "YouTube Lecture"),
                thumbnail_url=meta.get("thumbnail_url", ""),
            )

    if existing_status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ingestion for video '{video_id}' is currently in progress.",
        )

    mark_video_processing(video_id, target_url)

    try:
        tree = build_topic_tree_for_video(video_id)
        save_tree(tree)
        return IngestResponse(
            video_id=video_id,
            title=tree.title,
            duration=tree.duration,
            section_count=len(tree.sections),
            status="success",
            channel=meta.get("channel", "YouTube Lecture"),
            thumbnail_url=meta.get("thumbnail_url", ""),
        )
    except YouTubeServiceError as e:
        mark_video_failed(video_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except LLMClientError as e:
        mark_video_failed(video_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"LLM Ingestion Error: {str(e)}")
    except Exception as e:
        mark_video_failed(video_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unexpected Ingestion Failure: {str(e)}")


@app.get("/api/tree/{video_id}", response_model=TopicTree)
def get_topic_tree(video_id: str):
    """Fetch structured 2-level topic tree representation directly from SQLite database."""
    tree = load_tree(video_id)
    if not tree:
        current_status = get_video_status(video_id)
        if current_status == "processing":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Video '{video_id}' is currently processing.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No tree found for video '{video_id}'. Ingest video first.",
        )
    return tree


@app.get("/api/history/{video_id}", response_model=List[QueryHistoryItem])
def fetch_chat_history(video_id: str):
    """Fetch stored Q&A interaction history for a specific video or all videos."""
    return get_query_history(video_id)


@app.delete("/api/history")
def clear_chat_history(video_id: Optional[str] = None):
    """Clear chat Q&A history."""
    clear_query_history(video_id)
    return {"message": "Chat history cleared."}


@app.post("/api/query", response_model=QueryResponse)
def query_video(req: QueryRequest):
    """
    Execute vectorless RAG query. Supports querying a single video or 'all' videos simultaneously.
    """
    if req.video_id == "all":
        # Multi-Video Vectorless RAG across all ingested lectures
        ingested_items = list_ingested_videos()
        if not ingested_items:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No ingested video lectures found. Please ingest at least one lecture first.",
            )
        trees = []
        for item in ingested_items:
            t = load_tree(item.video_id)
            if t:
                trees.append(t)

        if not trees:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active lecture trees available for search.",
            )

        try:
            return answer_question_vectorless_multi(trees, req.question)
        except LLMClientError as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Multi-Video LLM Error: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Multi-Video Query Error: {str(e)}")

    # Single-video vectorless query
    tree = load_tree(req.video_id)
    if not tree:
        current_status = get_video_status(req.video_id)
        if current_status == "processing":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Video '{req.video_id}' is currently processing.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video '{req.video_id}' has not been ingested yet.",
        )

    try:
        response = answer_question_vectorless(tree, req.question)
        return response
    except LLMClientError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"LLM Retrieval Error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Query Execution Error: {str(e)}")


# Serve static web interface
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_index():
    """Serve SPA index html page."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Vectorless RAG API is running. Static UI not found."}
