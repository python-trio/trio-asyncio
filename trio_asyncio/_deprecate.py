# Mostly copied from trio._deprecate.

import sys
from functools import wraps
from types import ModuleType
import warnings

import attr


# We want our warnings to be visible by default (at least for now), but we
# also want it to be possible to override that using the -W switch. AFAICT
# this means we cannot inherit from DeprecationWarning, because the only way
# to make it visible by default then would be to add our own filter at import
# time, but that would override -W switches...
class TrioAsyncioDeprecationWarning(FutureWarning):
    """Warning emitted if you use deprecated trio-asyncio functionality.

    This inherits from `FutureWarning`, not `DeprecationWarning`, for the
    same reasons described for `trio.TrioDeprecationWarning`.
    """


def _url_for_issue(issue):
    return "https://github.com/python-trio/trio-asyncio/issues/{}".format(issue)


def _stringify(thing):
    if hasattr(thing, "__module__") and hasattr(thing, "__qualname__"):
        return "{}.{}".format(thing.__module__, thing.__qualname__)
    return str(thing)


def warn_deprecated(thing, version, *, issue, instead, stacklevel=2):
    stacklevel += 1
    msg = "{} is deprecated since trio-asyncio {}".format(_stringify(thing), version)
    if instead is None:
        msg += " with no replacement"
    else:
        msg += "; use {} instead".format(_stringify(instead))
    if issue is not None:
        msg += " ({})".format(_url_for_issue(issue))
    warnings.warn(TrioAsyncioDeprecationWarning(msg), stacklevel=stacklevel)


# @deprecated("0.2.0", issue=..., instead=...)
# def ...
def deprecated(version, *, thing=None, issue, instead):
    def do_wrap(fn):
        nonlocal thing

        @wraps(fn)
        def wrapper(*args, **kwargs):
            warn_deprecated(thing, version, instead=instead, issue=issue)
            return fn(*args, **kwargs)

        # If our __module__ or __qualname__ get modified, we want to pick up
        # on that, so we read them off the wrapper object instead of the (now
        # hidden) fn object
        if thing is None:
            thing = wrapper

        if wrapper.__doc__ is not None:
            doc = wrapper.__doc__
            doc = doc.rstrip()
            doc += "\n\n"
            doc += ".. deprecated:: {}\n".format(version)
            if instead is not None:
                doc += "   Use {} instead.\n".format(_stringify(instead))
            if issue is not None:
                doc += "   For details, see `issue #{} <{}>`__.\n".format(
                    issue, _url_for_issue(issue)
                )
            doc += "\n"
            wrapper.__doc__ = doc

        return wrapper

    return do_wrap


def deprecated_alias(old_qualname, new_fn, version, *, issue):
    @deprecated(version, issue=issue, instead=new_fn)
    @wraps(new_fn, assigned=("__module__", "__annotations__"))
    def wrapper(*args, **kwargs):
        "Deprecated alias."
        return new_fn(*args, **kwargs)

    wrapper.__qualname__ = old_qualname
    wrapper.__name__ = old_qualname.rpartition(".")[-1]
    return wrapper


@attr.s(frozen=True)
class DeprecatedAttribute:
    _not_set = object()

    value = attr.ib()
    version = attr.ib()
    issue = attr.ib()
    instead = attr.ib(default=_not_set)


class _ModuleWithDeprecations(ModuleType):
    def __getattr__(self, name):
        if name in self.__deprecated_attributes__:
            info = self.__deprecated_attributes__[name]
            instead = info.instead
            if instead is DeprecatedAttribute._not_set:
                instead = info.value
            thing = "{}.{}".format(self.__name__, name)
            warn_deprecated(thing, info.version, issue=info.issue, instead=instead)
            return info.value

        raise AttributeError(name)


def enable_attribute_deprecations(module_name):
    module = sys.modules[module_name]
    module.__class__ = _ModuleWithDeprecations
    # Make sure that this is always defined so that
    # _ModuleWithDeprecations.__getattr__ can access it without jumping
    # through hoops or risking infinite recursion.
    module.__deprecated_attributes__ = {}
