"""
Reject assignments to attribute names a class does not define.

Configuration in this package is done by setting attributes (``dca.min_h_b = 0.9``), so a
misspelled or renamed name would otherwise create a new, unused attribute and be ignored
silently. Classes using ``StrictAttributes`` accept any assignment while they are being
constructed (including in subclass ``__init__`` methods); once construction finishes,
assigning a name that is neither an instance attribute nor defined on the class raises
``AttributeError`` with the closest valid names.

Set ``_strict_attributes = False`` on a subclass to opt out.
"""

import difflib


class _StrictMeta(type):
    """Marks instances as constructed after the full ``__init__`` chain has run."""

    def __call__(cls, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        object.__setattr__(instance, "_constructed", True)
        return instance


class StrictAttributes(metaclass=_StrictMeta):
    _strict_attributes = True

    def _known_attribute(self, name: str) -> bool:
        # Look up the class dicts directly: ``hasattr`` would run property getters,
        # some of which have side effects (e.g. opening the run log).
        if name in self.__dict__:
            return True
        return any(name in klass.__dict__ for klass in type(self).__mro__)

    def __setattr__(self, name: str, value) -> None:
        if (
            self.__dict__.get("_constructed", False)
            and self._strict_attributes
            and not self._known_attribute(name)
        ):
            # Suggest settable names only: instance attributes and properties, not methods.
            known = set(self.__dict__)
            for klass in type(self).__mro__:
                known.update(
                    k for k, v in klass.__dict__.items()
                    if isinstance(v, property)
                    or not (callable(v) or isinstance(v, (staticmethod, classmethod)))
                )
            candidates = sorted(k for k in known if not k.startswith("__"))
            close = difflib.get_close_matches(name, candidates, n=3, cutoff=0.6)
            if not close:
                lowered = {c.lower(): c for c in candidates}
                close = [lowered[n] for n in difflib.get_close_matches(name.lower(), list(lowered), n=3, cutoff=0.6)]
            hint = f" Did you mean {', '.join(repr(c) for c in close)}?" if close else ""
            raise AttributeError(
                f"{type(self).__name__} has no attribute {name!r}; setting it would have no "
                f"effect.{hint}"
            )
        object.__setattr__(self, name, value)
