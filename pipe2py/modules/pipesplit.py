# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipesplit
    ~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=operators#Split
"""

# contributed by https://github.com/tuukka

from itertools import tee, imap
from copy import deepcopy


class Split(object):
    def __init__(self, context, _INPUT, conf, splits=2, **kwargs):
        # todo? tee is not threadsafe
        # todo: is 2 iterators always enough?
        iterators = tee(_INPUT, splits)

        # deepcopy each item passed along so that changes in one branch
        # don't affect the other branch
        self.iterators = (imap(deepcopy, iterator) for iterator in iterators)

    def __iter__(self):
        try:
            return self.iterators.next()
        except StopIteration:
            raise ValueError("split has 2 outputs, tried to activate third")


def pipe_split(context, _INPUT, conf, splits, **kwargs):
    """An operator that splits a source into identical copies. Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipe2py.modules pipe like object (iterable of items)
    conf : dict
    splits : number of copies

    Yields
    ------
    _OUTPUT, _OUTPUT2... : copies of all source items
    """
    return Split(context, _INPUT, conf, splits, **kwargs)
