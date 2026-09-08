"""Pydantic schemas for domain models, LLM structured outputs, and API contracts."""

from typing import List, Optional
from pydantic import BaseModel, Field


class TranscriptChunk(BaseModel):
    text: str
    start_ts: float
    duration: float
    end_ts: float


class LeafSpan(BaseModel):
    span_id: str
    start_ts: float
    end_ts: float
    text: str


class SubsectionNode(BaseModel):
    id: str
    title: str
    summary: str
    start_ts: float
    end_ts: float
    leaves: List[LeafSpan] = Field(default_factory=list)


class SectionNode(BaseModel):
    id: str
    title: str
    summary: str
    start_ts: float
    end_ts: float
    subsections: List[SubsectionNode] = Field(default_factory=list)


class TopicTree(BaseModel):
    video_id: str
    title: str
    duration: float
    sections: List[SectionNode] = Field(default_factory=list)
    created_at: Optional[str] = None


# --- LLM Structured Output Schemas ---

class SegmentationSubsection(BaseModel):
    title: str = Field(description="Descriptive title of this subtopic section")
    summary_hint: str = Field(description="Brief 1-line key takeaway for this subsection")
    block_start_index: int = Field(description="0-indexed start block position inclusive")
    block_end_index: int = Field(description="0-indexed end block position inclusive")


class SegmentationSection(BaseModel):
    title: str = Field(description="High-level topic section title")
    summary_hint: str = Field(description="Brief 1-line key takeaway for this main section")
    subsections: List[SegmentationSubsection] = Field(
        description="Subtopic segments covering this section's block range sequentially"
    )


class SegmentationResult(BaseModel):
    sections: List[SegmentationSection] = Field(
        description="List of top-level sections spanning the lecture sequentially without gaps"
    )


class NodeSummaryResult(BaseModel):
    summary: str = Field(description="Concise 2-3 sentence summary capturing core conceptual points")


class BranchSelectionResult(BaseModel):
    selected_node_ids: List[str] = Field(
        description="IDs of section or subsection nodes (e.g. 'sec_1', 'sec_1_sub_2') relevant to answering the prompt. Return multiple if the prompt spans multiple subtopics."
    )
    rationale: str = Field(description="One-sentence explanation of why these nodes were selected")


class TimestampMarker(BaseModel):
    start_ts: float = Field(description="Start time in seconds for the relevant clip")
    label: str = Field(description="Short descriptive label for what is discussed at this timestamp")
    video_id: Optional[str] = Field(default=None, description="Video ID if multi-video synthesis")


class VideoRoutingResult(BaseModel):
    selected_video_ids: List[str] = Field(
        description="List of video_ids relevant to answering the user question. Can select 1 or multiple videos."
    )
    rationale: str = Field(description="Brief explanation for why these videos were selected")


class AnswerSynthesisResult(BaseModel):
    answer: str = Field(description="Detailed answer synthesised directly from transcript text")
    timestamps: List[TimestampMarker] = Field(
        description="Exact timestamp markers corresponding to where key concepts were stated in the video"
    )


# --- API Request & Response Schemas ---

class IngestRequest(BaseModel):
    url: str


class BatchIngestRequest(BaseModel):
    urls: List[str]


class IngestResponse(BaseModel):
    video_id: str
    title: str
    duration: float
    section_count: int
    status: str
    channel: str = "YouTube Lecture"
    thumbnail_url: str = ""


class BatchIngestResponse(BaseModel):
    results: List[IngestResponse]


class QueryRequest(BaseModel):
    video_id: str  # specific video_id or "all" for multi-video query
    question: str


class QueryResponse(BaseModel):
    answer: str
    selected_nodes: List[str]
    rationale: str
    timestamps: List[TimestampMarker]
    video_url_with_timestamp: Optional[str] = None
    sources: List[str] = Field(default_factory=list)


class VideoItem(BaseModel):
    video_id: str
    title: str
    channel: str
    duration: float
    thumbnail_url: str
    processed_at: Optional[str] = None
    status: str
    summary: Optional[str] = None
    section_count: int = 0


class QueryHistoryItem(BaseModel):
    id: int
    video_id: str
    question: str
    answer: str
    selected_nodes: List[str]
    rationale: str
    timestamps: List[TimestampMarker]
    created_at: str


class SampleVideo(BaseModel):
    video_id: str
    title: str
    channel: str
    duration: float
    thumbnail_url: str
    description: str
    sample_questions: List[str]
