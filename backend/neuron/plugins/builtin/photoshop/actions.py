"""Builtin plugin actions: Photoshop."""

def open(args=None):
    from neuron.plugins._util import open_app
    return open_app('Photoshop')

def focus(args=None):
    from neuron.plugins._util import focus
    return focus('Photoshop')

