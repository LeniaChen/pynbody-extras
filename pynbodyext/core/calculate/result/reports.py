"""Text reports for a finished run: performance, cache, summary, pipeline.

These are the reports ``Result.report_*()`` returns.  They used to live in
``ResultRepr``, which is about how an object *renders* (its repr and HTML card); a
report is text a caller asks for, with its own layout and truncation rules, so it
lives here and ``repr.py`` stops growing every time a report gains a section.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pynbodyext.core.calculate.display import format_mem, format_time

from .query import ResultQuery

if TYPE_CHECKING:
    from .result import Result

__all__ = ["cache_section", "perf_table", "pipeline_report", "summary"]


def perf_table(
    result: Result[Any], *, show_ids: bool = False, max_depth: int | None = None, max_children: int | None = None
) -> str:
    ResultQuery._validate_tree_limits(max_depth, max_children)
    title = result.root.name or str(result.root.kind)
    lines: list[str] = [title] if title else []
    header = "Node                           | Phase           | Time         | Mem Used       | Peak Mem       | RSS Delta"
    lines.append("-" * len(header))
    lines.append(header)
    lines.append("-" * len(header))

    if max_depth is None and max_children is None:
        nodes = list(result.nodes.values())
        hidden_count = 0
    else:
        visible_nodes, hidden_count = ResultQuery._visible_tree_nodes(
            result, result.root, max_depth=max_depth, max_children=max_children
        )
        seen_node_ids: set[str] = set()
        nodes = []
        for node in visible_nodes:
            if node.node_id in seen_node_ids:
                continue
            seen_node_ids.add(node.node_id)
            nodes.append(node)

    for node in nodes:
        node_label = ResultQuery.node_label(node, show_ids=show_ids, show_ref=True, show_kind=True, max_width=30)
        for phase in node.run.phases:
            lines.append(
                f"{node_label:<30} | "
                f"{phase.phase[:15]:<15} | "
                f"{format_time(phase.elapsed_s):>12} | "
                f"{format_mem(phase.memory_used):>14} | "
                f"{format_mem(phase.memory_peak):>14} | "
                f"{format_mem(phase.rss_used):>10}"
            )

    if hidden_count:
        hidden_suffix = "node" if hidden_count == 1 else "nodes"
        hidden_label = f"... {hidden_count} {hidden_suffix} hidden"
        lines.append(f"{hidden_label[:30]:<30} | {'-':<15} | {'-':>12} | {'-':>14} | {'-':>14} | {'-':>10}")

    lines.append("-" * len(header))
    lines.append(
        f"{'Total':<30} | {'-':<15} | "
        f"{format_time(result.perf_summary.total_time_s):>12} | "
        f"{'-':>14} | {'-':>14} | {'-':>10}"
    )
    lines.append("-" * len(header))
    return "\n".join(lines)

# ── Cache section ──────────────────────────────────────────────────────────

def cache_section(result: Result[Any], *, max_events: int = 12) -> str:
    """Return the runtime cache report: the stored text plus recent events.

    ``result.reports["cache"]`` is the canonical text captured during the run;
    this only appends the diagnosis events that the stored text leaves out,
    so the report method and the ``Result`` card cannot drift apart.
    """
    stored = result.reports.get("cache", "").strip()
    lines = (
        [stored]
        if stored
        else [
            "Runtime Cache",
            f"entries: {result.perf_summary.cache_store_count}",
            f"hits: {result.perf_summary.cache_hit_count}",
            f"misses: {result.perf_summary.cache_miss_count}",
            f"stores: {result.perf_summary.cache_store_count}",
        ]
    )

    events = result.diagnostics.cache()
    if not events:
        return "\n".join(lines)

    lines.append("")
    lines.append("Recent events")
    for event in events[-max_events:]:
        if event.node_id and event.node_id in result.nodes:
            node = result.nodes[event.node_id]
            label = ResultQuery.node_label(node, show_ref=True, show_kind=True, max_width=48)
        else:
            label = "-"
        lines.append(f"- {event.event}: {label}")

    return "\n".join(lines)

# ── Summary ────────────────────────────────────────────────────────────────

def summary(result: Result[Any], *, include_cache_counts: bool = True) -> str:
    root_label = result.root.label
    lines = [
        f"root: {root_label}",
        f"value_type: {type(result.value).__name__}",
        f"nodes: {len(result.nodes)}",
        f"warnings: {len(result.warnings)}",
        f"errors: {len(result.errors)}",
    ]

    if result.perf_summary.total_time_s is not None:
        lines.append(f"total_time_s: {result.perf_summary.total_time_s:.6f}")
    else:
        lines.append("total_time_s: -")

    if include_cache_counts:
        lines.append(f"cache_hits: {result.perf_summary.cache_hit_count}")
        lines.append(f"cache_misses: {result.perf_summary.cache_miss_count}")
        lines.append(f"cache_stores: {result.perf_summary.cache_store_count}")
    return "\n".join(lines)

# ── Pipeline report ────────────────────────────────────────────────────────

def pipeline_report(
    result: Result[Any],
    *,
    include_perf: bool = True,
    include_trace: bool = False,
    include_cache: bool = False,
    include_errors: bool = True,
    include_execution_tree: bool = False,
    show_ids: bool = False,
    max_depth: int | None = None,
    max_children: int | None = None,
) -> str:
    sections: list[str] = [
        "Summary",
        summary(result),
        "Pipeline",
        ResultQuery.node_tree(result, show_ids=show_ids, max_depth=max_depth, max_children=max_children),
    ]

    if include_execution_tree:
        execution_text = ResultQuery.execution_tree(
            result, show_ids=show_ids, max_depth=max_depth, max_children=max_children
        ).strip()
        if execution_text:
            sections.extend(["Execution", execution_text])

    if include_perf:
        perf_text = perf_table(
            result, show_ids=show_ids, max_depth=max_depth, max_children=max_children
        ).strip()
        if perf_text:
            sections.extend(["Performance", perf_text])

    if include_trace:
        trace_text = result.report_trace_timeline(show_ids=show_ids).strip()
        if trace_text:
            sections.extend(["Trace Timeline", trace_text])

    if include_cache:
        cache_text = cache_section(result).strip()
        if cache_text:
            sections.extend(["Cache", cache_text])

    if include_errors and (result.errors or ResultQuery.find_error_nodes(result)):
        error_section: list[str] = []
        error_nodes = ResultQuery.find_error_nodes(result)

        if error_nodes:
            error_section.append("nodes:")
            for node in error_nodes:
                phase = node.run.error.phase if node.run.error is not None else None
                phase_suffix = f" phase={phase}" if phase else ""
                label = ResultQuery.node_label(node, show_ids=show_ids, show_ref=True, show_kind=True)
                error_section.append(f"- {label}{phase_suffix}")

        if result.errors:
            if error_section:
                error_section.append("")
                error_section.append("messages:")
            for err in result.errors:
                phase_suffix = f" (phase={err.phase})" if err.phase else ""
                error_section.append(f"- {err.error_type}: {err.message}{phase_suffix}")

        sections.extend(["Errors", "\n".join(error_section)])

    return "\n\n".join(section for section in sections if section)
