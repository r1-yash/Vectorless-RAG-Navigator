"""Vectorless 2-step LLM reasoning retrieval service."""

from typing import Dict, List, Tuple

from src.models import (
    TopicTree,
    QueryResponse,
    BranchSelectionResult,
    AnswerSynthesisResult,
    TimestampMarker,
    LeafSpan,
)
from src.services.llm_client import LLMClient


class RetrievalServiceError(Exception):
    """Raised when vectorless retrieval execution fails."""
    pass


from src.models import (
    TopicTree,
    QueryResponse,
    BranchSelectionResult,
    AnswerSynthesisResult,
    VideoRoutingResult,
    TimestampMarker,
    LeafSpan,
)
from src.services.llm_client import LLMClient
from src.services.storage import save_query_history


class RetrievalServiceError(Exception):
    """Raised when vectorless retrieval execution fails."""
    pass


def answer_question_vectorless(tree: TopicTree, question: str) -> QueryResponse:
    """
    Execute fixed 2-step vectorless RAG pipeline:
    Step 1: LLM reasoning over top 2 levels of tree summaries to pick target node IDs.
    Step 2: LLM synthesis over raw leaf text of target nodes to generate answer + timestamps.
    """
    groq_llm = LLMClient()

    # --- Step 1: Branch Selection ---
    rendered_tree_summary = _render_tree_summaries(tree)

    step1_system_prompt = (
        "You are an intelligent lecture navigation routing system. Given a 2-level topic tree (sections and subsections) "
        "of a video lecture, identify the node ID(s) that contain the information needed to answer the user's question. "
        "You may select 1 node for localized questions, or multiple nodes if the question spans several topics."
    )

    step1_user_prompt = (
        f"Lecture Title: {tree.title}\n\n"
        f"Topic Hierarchy & Summaries:\n{rendered_tree_summary}\n\n"
        f"User Question: '{question}'\n\n"
        f"Identify the relevant node ID(s) (e.g., 'sec_1_sub_2' or 'sec_2')."
    )

    branch_result: BranchSelectionResult = groq_llm.call_structured(
        system_prompt=step1_system_prompt,
        user_prompt=step1_user_prompt,
        response_model=BranchSelectionResult,
        temperature=0.1,
    )

    selected_ids = branch_result.selected_node_ids
    if not selected_ids:
        selected_ids = [tree.sections[0].id] if tree.sections else []

    # --- Step 2: Answer Synthesis ---
    retrieved_spans = _collect_leaf_spans(tree, selected_ids)
    
    if not retrieved_spans:
        retrieved_spans = _collect_all_spans(tree)[:4]

    context_text = _format_spans_for_context(retrieved_spans)

    step2_system_prompt = (
        "You are an accurate academic teaching assistant. Answer the user's question relying strictly on the provided "
        "lecture transcript excerpts. Cite exact timestamps (in seconds) for key facts stated in the transcript."
    )

    step2_user_prompt = (
        f"Lecture Title: {tree.title}\n"
        f"User Question: '{question}'\n\n"
        f"Retrieved Transcript Excerpts:\n{context_text}\n\n"
        f"Synthesize a clear, detailed answer to the question. Include specific timestamp markers corresponding to where "
        f"the information is delivered in the video."
    )

    synthesis_result: AnswerSynthesisResult = groq_llm.call_structured(
        system_prompt=step2_system_prompt,
        user_prompt=step2_user_prompt,
        response_model=AnswerSynthesisResult,
        temperature=0.2,
    )

    # Standardize timestamp objects with video_id
    for ts in synthesis_result.timestamps:
        ts.video_id = tree.video_id

    video_url_with_ts = None
    if synthesis_result.timestamps:
        first_ts = int(synthesis_result.timestamps[0].start_ts)
        video_url_with_ts = f"https://www.youtube.com/watch?v={tree.video_id}&t={first_ts}s"

    response = QueryResponse(
        answer=synthesis_result.answer,
        selected_nodes=selected_ids,
        rationale=branch_result.rationale,
        timestamps=synthesis_result.timestamps,
        video_url_with_timestamp=video_url_with_ts,
        sources=[tree.title],
    )

    # Persist Q&A turn into SQLite database history
    save_query_history(
        video_id=tree.video_id,
        question=question,
        answer=response.answer,
        selected_nodes=response.selected_nodes,
        rationale=response.rationale,
        timestamps=response.timestamps,
    )

    return response


def answer_question_vectorless_multi(trees: List[TopicTree], question: str) -> QueryResponse:
    """
    Execute 3-step Multi-Video Vectorless RAG pipeline:
    Step 0: LLM Video Routing across all ingested lectures using video titles & summaries.
    Step 1: LLM Branch Selection on chosen video topic trees.
    Step 2: LLM Synthesis across retrieved transcript spans across multiple videos.
    """
    if not trees:
        raise RetrievalServiceError("No ingested lecture trees available for multi-video query.")

    if len(trees) == 1:
        return answer_question_vectorless(trees[0], question)

    groq_llm = LLMClient()

    # --- Step 0: Video Routing ---
    video_overviews = []
    trees_by_id = {t.video_id: t for t in trees}
    for t in trees:
        sec_titles = ", ".join([s.title for s in t.sections[:5]])
        video_overviews.append(f"Video ID [{t.video_id}]: '{t.title}'\n  Key Topics: {sec_titles}")

    step0_system_prompt = (
        "You are an intelligent multi-lecture video router. Given a list of video lectures and their key topics, "
        "identify which video ID(s) contain relevant content to answer the user's question."
    )
    step0_user_prompt = (
        f"Available Video Lectures:\n" + "\n\n".join(video_overviews) + f"\n\n"
        f"User Question: '{question}'\n\n"
        f"Identify the relevant video ID(s)."
    )

    routing_res: VideoRoutingResult = groq_llm.call_structured(
        system_prompt=step0_system_prompt,
        user_prompt=step0_user_prompt,
        response_model=VideoRoutingResult,
        temperature=0.1,
    )

    selected_video_ids = [vid for vid in routing_res.selected_video_ids if vid in trees_by_id]
    if not selected_video_ids:
        selected_video_ids = [trees[0].video_id]

    target_trees = [trees_by_id[vid] for vid in selected_video_ids]

    # --- Step 1: Branch Selection across candidate trees ---
    all_selected_nodes = []
    combined_spans_with_source = []

    for t in target_trees:
        rendered_summary = _render_tree_summaries(t)
        step1_sys = "Identify node ID(s) in this specific video tree relevant to the prompt."
        step1_user = f"Video: '{t.title}'\nTree:\n{rendered_summary}\n\nQuestion: '{question}'"
        
        branch_res: BranchSelectionResult = groq_llm.call_structured(
            system_prompt=step1_sys,
            user_prompt=step1_user,
            response_model=BranchSelectionResult,
            temperature=0.1,
        )
        s_ids = branch_res.selected_node_ids or ([t.sections[0].id] if t.sections else [])
        all_selected_nodes.extend([f"{t.video_id}:{nid}" for nid in s_ids])

        spans = _collect_leaf_spans(t, s_ids) or _collect_all_spans(t)[:4]
        for sp in spans:
            combined_spans_with_source.append((t.title, t.video_id, sp))

    # --- Step 2: Answer Synthesis ---
    context_lines = []
    for title, vid, sp in combined_spans_with_source:
        m, s = divmod(int(sp.start_ts), 60)
        context_lines.append(f"[{title} | ID:{vid} | {m:02d}:{s:02d} ({sp.start_ts:.0f}s)]: {sp.text}")

    context_text = "\n".join(context_lines[:25])  # Cap context to reasonable length

    step2_sys = (
        "You are an academic research assistant synthesizing insights across multiple video lectures. "
        "Answer the question clearly, referencing which lecture and timestamp each concept comes from."
    )
    step2_user = (
        f"User Question: '{question}'\n\n"
        f"Excerpts from Multiple Lectures:\n{context_text}\n\n"
        f"Provide a comprehensive answer with timestamp markers."
    )

    synthesis_res: AnswerSynthesisResult = groq_llm.call_structured(
        system_prompt=step2_sys,
        user_prompt=step2_user,
        response_model=AnswerSynthesisResult,
        temperature=0.2,
    )

    # Attach primary video_id to timestamps if missing
    for ts in synthesis_res.timestamps:
        if not ts.video_id and target_trees:
            ts.video_id = target_trees[0].video_id

    sources_list = [t.title for t in target_trees]
    first_vid = target_trees[0].video_id if target_trees else "all"
    first_ts = int(synthesis_res.timestamps[0].start_ts) if synthesis_res.timestamps else 0
    url_with_ts = f"https://www.youtube.com/watch?v={first_vid}&t={first_ts}s" if first_vid != "all" else None

    response = QueryResponse(
        answer=synthesis_res.answer,
        selected_nodes=all_selected_nodes,
        rationale=routing_res.rationale,
        timestamps=synthesis_res.timestamps,
        video_url_with_timestamp=url_with_ts,
        sources=sources_list,
    )

    save_query_history(
        video_id="all",
        question=question,
        answer=response.answer,
        selected_nodes=response.selected_nodes,
        rationale=response.rationale,
        timestamps=response.timestamps,
    )

    return response


def _render_tree_summaries(tree: TopicTree) -> str:
    """Format level-1 sections and level-2 subsections with concise summaries into a clean text block."""
    lines = []
    for sec in tree.sections:
        lines.append(f"Section [{sec.id}]: {sec.title} ({sec.start_ts:.0f}s - {sec.end_ts:.0f}s)")
        lines.append(f"  Summary: {sec.summary}")
        for sub in sec.subsections:
            lines.append(f"  Subsection [{sub.id}]: {sub.title} ({sub.start_ts:.0f}s - {sub.end_ts:.0f}s)")
            lines.append(f"    Summary: {sub.summary}")
        lines.append("")
    return "\n".join(lines)


def _collect_leaf_spans(tree: TopicTree, target_node_ids: List[str]) -> List[LeafSpan]:
    """Traverse topic tree and collect leaves belonging to selected node IDs."""
    target_set = set(target_node_ids)
    spans: List[LeafSpan] = []

    for sec in tree.sections:
        if sec.id in target_set:
            # Entire section selected; collect all child subsection leaves
            for sub in sec.subsections:
                spans.extend(sub.leaves)
        else:
            for sub in sec.subsections:
                if sub.id in target_set:
                    spans.extend(sub.leaves)

    return spans


def _collect_all_spans(tree: TopicTree) -> List[LeafSpan]:
    spans = []
    for sec in tree.sections:
        for sub in sec.subsections:
            spans.extend(sub.leaves)
    return spans


def _format_spans_for_context(spans: List[LeafSpan]) -> str:
    lines = []
    for span in spans:
        m, s = divmod(int(span.start_ts), 60)
        time_str = f"{m:02d}:{s:02d}"
        lines.append(f"[{time_str} / {span.start_ts:.0f}s - {span.end_ts:.0f}s]: {span.text}")
    return "\n".join(lines)
