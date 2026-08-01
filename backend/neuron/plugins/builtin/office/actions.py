"""Builtin plugin actions: Microsoft Office."""

def word(args=None):
    from neuron.plugins._util import open_app
    return open_app('WINWORD')

def excel(args=None):
    from neuron.plugins._util import open_app
    return open_app('EXCEL')

def powerpoint(args=None):
    from neuron.plugins._util import open_app
    return open_app('POWERPNT')

