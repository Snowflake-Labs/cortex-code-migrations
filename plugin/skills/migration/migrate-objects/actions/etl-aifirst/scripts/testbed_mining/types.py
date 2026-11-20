"""Neutral type categorization: a Snowflake type name plus the category flags the
Testbed boundary calculator and table builder read (`is_integer`, `is_number`,
`is_string`, `is_date`, `is_boolean`, `is_binary`).

An adapter maps its own platform type codes to a `TypeKind` and calls `make_type`.
The flags are DERIVED from the kind here, in one place, so two adapters can never
disagree about what "integer" means for the consumer.
"""

from __future__ import annotations

from dataclasses import dataclass

INTEGER = "integer"
NUMBER = "number"
STRING = "string"
DATE = "date"
BOOLEAN = "boolean"
BINARY = "binary"
OTHER = "other"


@dataclass(frozen=True)
class TypeInfo:
    name: str  # Snowflake type name, e.g. NUMBER, VARCHAR, TIMESTAMP
    kind: str  # one of the kind constants above
    precision: int | None = None
    scale: int | None = None

    @property
    def is_integer(self) -> bool:
        return self.kind == INTEGER

    @property
    def is_number(self) -> bool:
        # Integers are numbers too; the consumer's boundary calculator checks is_integer first.
        return self.kind in (INTEGER, NUMBER)

    @property
    def is_string(self) -> bool:
        return self.kind == STRING

    @property
    def is_date(self) -> bool:
        return self.kind == DATE

    @property
    def is_boolean(self) -> bool:
        return self.kind == BOOLEAN

    @property
    def is_binary(self) -> bool:
        return self.kind == BINARY


def make_type(
    name: str, kind: str, precision: int | None = None, scale: int | None = None
) -> TypeInfo:
    return TypeInfo(name=name, kind=kind, precision=precision, scale=scale)


UNKNOWN = TypeInfo(name="VARIANT", kind=OTHER)
