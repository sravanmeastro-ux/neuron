"""Builtin plugin actions: Steam."""

def open(args=None):
    from neuron.plugins._util import open_app
    return open_app('Steam')

def focus(args=None):
    from neuron.plugins._util import focus
    return focus('Steam')

