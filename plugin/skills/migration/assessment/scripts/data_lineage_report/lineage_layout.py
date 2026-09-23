"""Pure geometry, icon-mapping, and highlight helpers for the Data Lineage tab.

Cards and edges share one unscaled pixel coordinate space — the constants and
formulas below are copied exactly from the locked dashboard spec
(`lineage-layout.ts`) so a card's border and its edge's endpoint always agree,
without any `viewBox` scaling. `layout_lineage` is the single source of truth
for coordinates; the HTML renderer and its tests both call it rather than
duplicating the arithmetic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set

NODE_WIDTH = 184
NODE_MAX_WIDTH = 320
NODE_HEIGHT = 84
ROW_GAP = 24
CHILD_INSET = 20
# The expand control is a sibling of the card it belongs to (a card is
# `role="button"` and may not contain one), so its offset from that card's
# right/bottom edge is layout, not card padding.
TOGGLE_INSET_X = 8
TOGGLE_INSET_Y = 6
CANVAS_PADDING = 16
LANE_CARD_INSET = 8
LANE_GAP = 12
LANE_HEADER_HEIGHT = 90
BUCKET_HEADER_HEIGHT = 42
BUCKET_GAP = 12
BUCKET_CARD_INSET = 8
MIN_CANVAS_HEIGHT = 240

_LANES = ("source", "pipeline", "target", "report")
# Sources, Pipelines, and Targets are the canvas: they hold a header even with
# nothing in them, because an empty one is itself the finding (no pipeline
# writes anything, nothing was read). Reports is optional -- a project that
# assessed no reporting files has nothing to put there, and an empty fourth
# lane reads as a lane that failed to load rather than as an absence of data.
_ALWAYS_ON_LANES = frozenset(("source", "pipeline", "target"))

# Lane header icons are fixed by lane, independent of card contents.
LANE_HEADER_ICON: Dict[str, str] = {
    "source": "Database",
    "pipeline": "DataPipelines",
    "target": "Database",
    "report": "CloudSaas",
}


@dataclass(frozen=True)
class CardLayout:
    """One card's pixel box. `row` is the zero-based index within its bucket;
    first-seen JSON order is preserved inside each bucket."""

    id: str
    lane: str
    col: int
    row: int
    x: int
    y: int
    parent_id: Optional[str] = None


@dataclass(frozen=True)
class LaneLayout:
    lane: str
    col: int
    x: int
    width: int
    item_count: int


@dataclass(frozen=True)
class BucketLayout:
    lane: str
    key: str
    title: str
    x: int
    y: int
    width: int
    height: int
    item_count: int


@dataclass(frozen=True)
class LineageLayout:
    canvas_width: int
    width: int
    height: int
    card_width: int
    card_height: int
    lanes: Dict[str, LaneLayout]
    buckets: Dict[str, List[BucketLayout]]
    cards: Dict[str, CardLayout]


def bucket_key(node: Mapping[str, object]) -> str:
    """Resolve the platform bucket for one node without parsing Id or Label."""
    if str(node.get("Kind", "")).strip().lower() == "unresolved":
        return "Unresolved"
    platform = str(node.get("Platform") or "").strip()
    return platform or "Unknown"


def bucket_title(key: str) -> str:
    """Humanize a bucket key for the HTML header; unknown keys pass through unchanged."""
    return {"SqlServer": "SQL Server", "Ssis": "SSIS", "PowerBI": "Power BI"}.get(key, key)


def _order_bucket_keys(keys_in_order: List[str]) -> List[str]:
    """Keep first-seen platform order but pin Unknown then Unresolved to the lane tail."""
    normal = [key for key in keys_in_order if key not in ("Unknown", "Unresolved")]
    trailing: List[str] = []
    if "Unknown" in keys_in_order:
        trailing.append("Unknown")
    if "Unresolved" in keys_in_order:
        trailing.append("Unresolved")
    return normal + trailing


def _bucket_stack_height(card_count: int) -> int:
    if card_count <= 0:
        return 0
    return BUCKET_HEADER_HEIGHT + card_count * NODE_HEIGHT + max(0, card_count - 1) * ROW_GAP


def _parent_id(node: Mapping[str, object]) -> Optional[str]:
    parent = node.get("ParentId")
    if parent is None:
        return None
    parent_id = str(parent).strip()
    return parent_id or None


def layout_lineage(nodes: Sequence[Mapping[str, object]], canvas_width: int = 1160) -> LineageLayout:
    """Place every node with a recognized Lane into platform buckets, preserving
    JSON order within each bucket. Nodes with an unrecognized Lane are dropped —
    they never get a card and never count toward any lane's `item_count`. A
    repeated Id (malformed artifact) is placed only on its first occurrence,
    so a later duplicate never inflates row/height accounting or gets a
    second, overlapping card. Detail nodes (those with `ParentId`) are placed
    below their parent for edge geometry but do not affect collapsed bucket,
    lane, or canvas height accounting. `lanes` and `buckets` carry only the
    lanes actually drawn: the three core lanes always, and an optional lane
    (Reports) only when a node lands in it."""
    grouped: Dict[str, List[Mapping[str, object]]] = {lane: [] for lane in _LANES}
    detail_nodes: List[Mapping[str, object]] = []
    occupied_lanes: Set[str] = set()
    seen_ids: Set[str] = set()
    for node in nodes:
        lane = node.get("Lane")
        if lane not in grouped:
            continue
        node_id = str(node.get("Id"))
        if node_id in seen_ids:
            continue
        seen_ids.add(node_id)
        occupied_lanes.add(str(lane))
        if _parent_id(node) is not None:
            detail_nodes.append(node)
        else:
            grouped[lane].append(node)

    # Lane count drives every horizontal measure, so an omitted optional lane
    # gives its width back to the lanes that remain instead of leaving a gap.
    drawn_lanes = [lane for lane in _LANES if lane in _ALWAYS_ON_LANES or lane in occupied_lanes]
    usable = canvas_width - 2 * CANVAS_PADDING - (len(drawn_lanes) - 1) * LANE_GAP
    lane_width = max(NODE_WIDTH + 2 * LANE_CARD_INSET, usable // len(drawn_lanes))
    card_width = min(NODE_MAX_WIDTH, lane_width - 2 * LANE_CARD_INSET)
    card_x_offset = round((lane_width - card_width) / 2)

    def lane_x(col: int) -> int:
        return CANVAS_PADDING + col * (lane_width + LANE_GAP)

    lanes: Dict[str, LaneLayout] = {}
    buckets: Dict[str, List[BucketLayout]] = {lane: [] for lane in drawn_lanes}
    cards: Dict[str, CardLayout] = {}
    lane_content_heights: List[int] = []
    for col, lane in enumerate(drawn_lanes):
        items = grouped[lane]
        lanes[lane] = LaneLayout(lane=lane, col=col, x=lane_x(col), width=lane_width, item_count=len(items))
        card_x = lane_x(col) + card_x_offset
        bucket_order: List[str] = []
        bucket_nodes: Dict[str, List[Mapping[str, object]]] = {}
        for node in items:
            key = bucket_key(node)
            if key not in bucket_nodes:
                bucket_order.append(key)
                bucket_nodes[key] = []
            bucket_nodes[key].append(node)

        y = CANVAS_PADDING + LANE_HEADER_HEIGHT
        lane_content_height = 0
        ordered_keys = _order_bucket_keys(bucket_order)
        for bucket_index, key in enumerate(ordered_keys):
            nodes_in_bucket = bucket_nodes[key]
            stack_height = _bucket_stack_height(len(nodes_in_bucket))
            bucket = BucketLayout(
                lane=lane,
                key=key,
                title=bucket_title(key),
                x=lane_x(col),
                y=y,
                width=lane_width,
                height=stack_height,
                item_count=len(nodes_in_bucket),
            )
            buckets[lane].append(bucket)
            for row, node in enumerate(nodes_in_bucket):
                node_id = str(node.get("Id"))
                cards[node_id] = CardLayout(
                    id=node_id,
                    lane=lane,
                    col=col,
                    row=row,
                    x=card_x,
                    y=y + BUCKET_HEADER_HEIGHT + row * (NODE_HEIGHT + ROW_GAP),
                )
            y += stack_height
            lane_content_height += stack_height
            if bucket_index < len(ordered_keys) - 1:
                y += BUCKET_GAP
                lane_content_height += BUCKET_GAP
        lane_content_heights.append(lane_content_height)

    children_by_parent: Dict[str, List[Mapping[str, object]]] = {}
    for node in detail_nodes:
        parent_id = _parent_id(node)
        if parent_id is None:
            continue
        parent = cards.get(parent_id)
        if parent is None or str(node.get("Lane")) != parent.lane:
            continue
        children_by_parent.setdefault(parent_id, []).append(node)

    for parent_id, children in children_by_parent.items():
        parent = cards[parent_id]
        for child_index, node in enumerate(children):
            node_id = str(node.get("Id"))
            cards[node_id] = CardLayout(
                id=node_id,
                lane=parent.lane,
                col=parent.col,
                row=parent.row,
                x=parent.x + CHILD_INSET,
                y=parent.y + (child_index + 1) * (NODE_HEIGHT + ROW_GAP),
                parent_id=parent_id,
            )

    height = max(
        MIN_CANVAS_HEIGHT,
        2 * CANVAS_PADDING + LANE_HEADER_HEIGHT + max(lane_content_heights, default=0),
    )
    width = lane_x(len(drawn_lanes) - 1) + lane_width + CANVAS_PADDING

    return LineageLayout(
        canvas_width=canvas_width,
        width=width,
        height=height,
        card_width=card_width,
        card_height=NODE_HEIGHT,
        lanes=lanes,
        buckets=buckets,
        cards=cards,
    )


@dataclass(frozen=True)
class EdgeGeometry:
    from_id: str
    to_id: str
    x1: int
    y1: int
    x2: int
    y2: int
    d: str


def edge_path(edge: Mapping[str, object], layout: LineageLayout) -> Optional[EdgeGeometry]:
    """Build the cubic-bezier anchor geometry for one Canvas edge. Returns None
    (skip, don't raise) for: a self-loop; an endpoint outside the laid-out,
    visible node ids (a dangling reference, or a node dropped for having an
    unrecognized Lane); or an edge that isn't strictly left-to-right (the
    canvas only ever draws source -> pipeline -> target, so a backwards or
    same-lane edge doesn't fit the model). From/To are stringified before
    lookup so a numeric artifact id still matches `layout.cards`, which is
    always keyed by `str(Id)`."""
    from_raw = edge.get("From")
    to_raw = edge.get("To")
    if from_raw is None or to_raw is None:
        return None
    from_id = str(from_raw)
    to_id = str(to_raw)
    if not from_id or not to_id or from_id == to_id:
        return None
    source = layout.cards.get(from_id)
    target = layout.cards.get(to_id)
    if source is None or target is None or target.col <= source.col:
        return None

    half_height = layout.card_height // 2
    x1 = source.x + layout.card_width
    y1 = source.y + half_height
    x2 = target.x
    y2 = target.y + half_height
    mid_x = (x1 + x2) / 2
    d = f"M {x1} {y1} C {mid_x} {y1}, {mid_x} {y2}, {x2} {y2}"
    return EdgeGeometry(from_id=from_id, to_id=to_id, x1=x1, y1=y1, x2=x2, y2=y2, d=d)


@dataclass(frozen=True)
class ConnectedLineage:
    selected: Optional[str]
    upstream: FrozenSet[str]
    downstream: FrozenSet[str]
    path: FrozenSet[str]


def connected_lineage(
    selected_id: Optional[str],
    edges: Iterable[Mapping[str, object]],
    visible_ids: Iterable[str],
) -> ConnectedLineage:
    """Walk edges in both directions from `selected_id`, restricted to
    `visible_ids`, mirroring the click-to-highlight behavior the JS
    re-implements in the browser. A falsy/absent selection (or one outside
    the visible set) clears the highlight entirely. Ids are stringified
    consistently with `layout_lineage`/`edge_path`, so a numeric id still
    matches."""
    visible = {str(v) for v in visible_ids}
    selected = str(selected_id) if selected_id else None
    if not selected or selected not in visible:
        return ConnectedLineage(selected=None, upstream=frozenset(), downstream=frozenset(), path=frozenset())

    forward: Dict[str, Set[str]] = {}
    backward: Dict[str, Set[str]] = {}
    for e in edges:
        f_raw = e.get("From")
        t_raw = e.get("To")
        if f_raw is None or t_raw is None:
            continue
        f = str(f_raw)
        t = str(t_raw)
        if not f or not t or f == t or f not in visible or t not in visible:
            continue
        forward.setdefault(f, set()).add(t)
        backward.setdefault(t, set()).add(f)

    def walk(start: str, adjacency: Mapping[str, Set[str]]) -> Set[str]:
        seen: Set[str] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            for nxt in adjacency.get(current, ()):
                if nxt != start and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    downstream = walk(selected, forward)
    upstream = walk(selected, backward)
    return ConnectedLineage(
        selected=selected,
        upstream=frozenset(upstream),
        downstream=frozenset(downstream),
        path=frozenset(downstream | upstream),
    )


@dataclass(frozen=True)
class LineageView:
    selected_id: Optional[str]
    active_ids: FrozenSet[str]
    visible_ids: FrozenSet[str]
    connected: ConnectedLineage


def _node_id(node: Mapping[str, object]) -> str:
    return str(node.get("Id") or node.get("id") or "")


def _parent_id(node: Mapping[str, object]) -> Optional[str]:
    raw = node.get("ParentId")
    if raw is None:
        raw = node.get("parentId")
    parent = str(raw).strip() if raw is not None else ""
    return parent or None


def _edge_ends(edge: Mapping[str, object]) -> Optional[tuple[str, str]]:
    f_raw = edge.get("From")
    if f_raw is None:
        f_raw = edge.get("from")
    t_raw = edge.get("To")
    if t_raw is None:
        t_raw = edge.get("to")
    if f_raw is None or t_raw is None:
        return None
    f, t = str(f_raw), str(t_raw)
    if not f or not t:
        return None
    return f, t


def compose_lineage_view(
    nodes: Iterable[Mapping[str, object]],
    edges: Iterable[Mapping[str, object]],
    expanded_parents: Iterable[str],
    selected_id: Optional[str],
) -> LineageView:
    """Grain-then-focus composition used by `dlApplyView`.

    Active edges are the visible grain; reachability walks those edges among
    active ids; an expanded parent stays visible only as a container when a
    child survived focus, never because the walk reached it.
    """
    nodes_by_id = {_node_id(n): n for n in nodes if _node_id(n)}
    expanded = {str(p) for p in expanded_parents}
    children_by_parent: Dict[str, List[str]] = {}
    for node_id, node in nodes_by_id.items():
        parent = _parent_id(node)
        if parent:
            children_by_parent.setdefault(parent, []).append(node_id)

    active_ids: Set[str] = set()
    for node_id, node in nodes_by_id.items():
        parent = _parent_id(node)
        if parent:
            if parent in expanded:
                active_ids.add(node_id)
        elif node_id not in expanded:
            active_ids.add(node_id)

    active_edges: List[Mapping[str, object]] = []
    for edge in edges:
        ends = _edge_ends(edge)
        if ends is None:
            continue
        from_id, to_id = ends
        if from_id in expanded or to_id in expanded:
            continue
        from_parent = _parent_id(nodes_by_id[from_id]) if from_id in nodes_by_id else None
        to_parent = _parent_id(nodes_by_id[to_id]) if to_id in nodes_by_id else None
        if from_parent:
            if from_parent not in expanded:
                continue
        elif to_parent and to_parent not in expanded:
            continue
        active_edges.append({"From": from_id, "To": to_id})

    selected = str(selected_id) if selected_id else None
    if selected and selected not in active_ids:
        selected = None
    connected = connected_lineage(selected, active_edges, active_ids)

    visible: Set[str] = set()
    focused = bool(connected.selected)
    for node_id, node in nodes_by_id.items():
        parent = _parent_id(node)
        if parent:
            if parent not in expanded:
                continue
        elif node_id in expanded:
            continue
        if focused and node_id != connected.selected and node_id not in connected.path:
            continue
        visible.add(node_id)
    for parent_id in expanded:
        if parent_id not in nodes_by_id:
            continue
        if not focused:
            visible.add(parent_id)
            continue
        if any(child_id in visible for child_id in children_by_parent.get(parent_id, ())):
            visible.add(parent_id)

    return LineageView(
        selected_id=connected.selected,
        active_ids=frozenset(active_ids),
        visible_ids=frozenset(visible),
        connected=connected,
    )


def icon_name(kind: str, label: str, platform: Optional[str] = None) -> str:
    """Map a node's Kind (and, for `system`, its Platform then Label) to the
    dashboard's Stellar-equivalent icon contract. Python cannot import
    `@snowflake/stellar-icons`, so the renderer inlines each mapped name as SVG.

    Database-grain cards put the system key on Platform and the database name
    on Label, so Platform has to win or Files/SAP/XML cards get a Database icon.
    """
    kind_lower = (kind or "").strip().lower()
    if kind_lower in ("etl_pipeline", "etl_system", "etl_package"):
        return "DataPipelines"
    if kind_lower in ("report_system", "report_report"):
        return "CloudSaas"
    if kind_lower == "unresolved":
        return "Unknown"
    if kind_lower == "system":
        key = ((platform if platform not in (None, "") else label) or "").strip().lower()
        if key in ("files", "xml"):
            return "File"
        if key == "sap":
            return "CloudSaas"
        return "Database"
    return "Unknown"
