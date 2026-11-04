"""The neutral mining model. No platform vocabulary lives here.

Every field maps onto the Synthetic Testbed reader contract
(`Snowflake.SnowConvert.Testbed/Spec/Models/TestbedArtifact.cs`); the snake_case
rendering is `artifacts.py`'s job, not the adapter's. An adapter fills these from
whatever its document states and leaves a field empty rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from testbed_mining.types import TypeInfo


@dataclass(frozen=True)
class TableIdentity:
    """What a source table is called, and how sure the adapter is.

    `name` is the identity as the source states it (`[dbo].[Orders]`,
    `dbo.Orders`). `database` is the catalog the document binds it to, when it
    states one. `is_fallback` is True when the document named no table at all and the
    adapter used the reading element's own name -- that is not a real table identity, so
    it is never database-qualified and never matched against SQL DDL.
    """

    name: str
    database: str | None = None
    is_fallback: bool = False

    def rendered(self, qualify_with_database: bool) -> str:
        if qualify_with_database and self.database and not self.is_fallback:
            return f"[{self.database}].{self.name}"
        return self.name


@dataclass(frozen=True)
class MinedColumn:
    name: str
    type: TypeInfo
    # Only set when the document DECLARES them (a schema's nullable/key flags); None = not stated,
    # which the serializer renders as the honest default (nullable, not a key).
    nullable: bool | None = None
    primary_key: bool | None = None
    unique: bool | None = None


@dataclass
class MinedTable:
    identity: TableIdentity
    columns: list[MinedColumn]
    # The element that READS this table, cited so a reviewer can find it in the source.
    origin: str = ""


@dataclass(frozen=True)
class ColumnRef:
    """A column a branch predicate references, resolved to its originating table."""

    table: TableIdentity
    column: str
    type: TypeInfo


@dataclass
class PredicateNode:
    """Same shape as the consumer's ArtifactPredicateNode: an atom or an and/or connective."""

    kind: str  # "atom" | "and" | "or"
    columns: list[str] | None = None
    operator: str | None = None
    values: list[str] | None = None
    children: list[PredicateNode] | None = None


@dataclass
class Branch:
    branch_id: int
    construct_kind: str
    predicate_text: str
    columns: list[ColumnRef]
    predicate: PredicateNode | None
    line: int = 0
    origin: str = ""


@dataclass
class JoinEdge:
    left_table: TableIdentity | None
    left_columns: list[str]
    right_table: TableIdentity | None
    right_columns: list[str]
    join_type: str  # "inner" | "left" | "full" | ...
    is_anti: bool = False
    origin: str = ""


@dataclass
class SemiAnti:
    kind: str  # "ANTI" | "SEMI"
    table: TableIdentity | None
    columns: list[str]
    origin: str = ""


@dataclass
class MinedPackage:
    """The procedural (PACKAGE) artifact: everything mined from the document's logic."""

    object_name: str
    object_type: str = "PACKAGE"
    branches: list[Branch] = field(default_factory=list)
    edges: list[JoinEdge] = field(default_factory=list)
    semi_anti: list[SemiAnti] = field(default_factory=list)
    derived_columns: list[str] = field(default_factory=list)

    def has_signal(self) -> bool:
        return bool(
            self.branches or self.edges or self.semi_anti or self.derived_columns
        )


@dataclass
class MiningResult:
    platform: str
    document: str
    package: MinedPackage
    tables: list[MinedTable]
    # Free-form, human-readable facts the adapter wants on record (unresolved operands,
    # IR disagreements, skipped components). Written to the manifest, never to an artifact.
    diagnostics: list[str] = field(default_factory=list)
    # Which inputs the adapter actually consumed, e.g. {"document": True, "ir": False}.
    inputs: dict[str, bool] = field(default_factory=dict)
    # Source graph / naming context a reviewer needs to see how a column was qualified (flows,
    # source elements, per-flow column lineage). Manifest-only, like diagnostics; empty = omitted.
    context: dict = field(default_factory=dict)
