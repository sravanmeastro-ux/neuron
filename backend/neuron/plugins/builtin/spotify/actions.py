"""Builtin plugin actions: Spotify."""

def open(args=None):
    from neuron.plugins._util import open_app
    return open_app('Spotify')

def focus(args=None):
    from neuron.plugins._util import focus
    return focus('Spotify')

