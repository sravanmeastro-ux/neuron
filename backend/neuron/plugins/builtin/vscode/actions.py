"""Builtin plugin actions: VS Code."""

def open(args=None):
    from neuron.plugins._util import open_app
    return open_app('Code')

def focus(args=None):
    from neuron.plugins._util import focus
    return focus('Code')

