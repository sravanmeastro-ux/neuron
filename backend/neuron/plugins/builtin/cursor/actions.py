"""Builtin plugin actions: Cursor."""

def open(args=None):
    from neuron.plugins._util import open_app
    return open_app('Cursor')

def focus(args=None):
    from neuron.plugins._util import focus
    return focus('Cursor')

