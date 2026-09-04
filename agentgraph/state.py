"""State merging: a node returns only what changed, the SCHEMA says how to join it.

This is the piece LangGraph spells as ``Annotated[list, operator.add]``. Here the
reducer is an ordinary function and the schema is an ordinary dict, so you can
read it.
"""


def add(old, new):
    """Concatenate lists. For fields that accumulate, like a list of findings."""
    return (old or []) + (new or [])


def replace(old, new):
    """The new value wins. The default for everything that does not accumulate."""
    return new


def merge(state: dict, delta: dict, schema: dict) -> dict:
    """Merge ``delta`` into ``state``, field by field, using ``schema``.

    A field the node did not return stays exactly as it was. That is the rule
    people get wrong: the node's return value is not the new state, it is a
    description of what changed.

    A field that is not in the schema raises. A typo in a node's return value
    should fail here, not become a ghost field three steps later.
    """
    merged = dict(state)
    for key, value in delta.items():
        if key not in schema:
            raise KeyError(f"field {key!r} is not in the SCHEMA")
        merged[key] = schema[key](state.get(key), value)
    return merged
