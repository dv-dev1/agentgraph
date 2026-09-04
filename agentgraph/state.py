"""Merging a node's return value into the state."""


def add(old, new):
    return (old or []) + (new or [])


def replace(old, new):
    return new


def merge(state: dict, delta: dict, schema: dict) -> dict:
    """A field the node did not return stays as it was; one outside the schema raises."""
    merged = dict(state)
    for key, value in delta.items():
        if key not in schema:
            raise KeyError(f"field {key!r} is not in the SCHEMA")
        merged[key] = schema[key](state.get(key), value)
    return merged
