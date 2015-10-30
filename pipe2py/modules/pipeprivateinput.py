# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipeprivateinput
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=user_inputs#PrivateText
"""

from pipe2py.lib import utils


def pipe_privateinput(context=None, _INPUT=None, conf=None, **kwargs):
    """An input that prompts the user for some text and yields it forever.
    Not loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : unused
    conf : {
        'name': {'value': 'parameter name'},
        'prompt': {'value': 'User prompt'},
        'default': {'value': 'default value'},
        'debug': {'value': 'debug value'}
    }

    Yields
    ------
    _OUTPUT : text
    """
    value = utils.get_input(context, conf)

    while True:
        yield value
