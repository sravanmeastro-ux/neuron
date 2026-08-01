"""Builtin plugin actions: OBS Studio."""

def open(args=None):
    from neuron.plugins._util import open_app
    return open_app('OBS Studio')

def focus(args=None):
    from neuron.plugins._util import focus
    return focus('OBS Studio')

