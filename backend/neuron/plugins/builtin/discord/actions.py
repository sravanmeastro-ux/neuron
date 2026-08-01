"""Builtin plugin actions: Discord."""

def open(args=None):
    from neuron.plugins._util import open_app
    return open_app('Discord')

def focus(args=None):
    from neuron.plugins._util import focus
    return focus('Discord')

