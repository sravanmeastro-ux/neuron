"""Builtin plugin actions: Blender."""

def open(args=None):
    from neuron.plugins._util import open_app
    return open_app('Blender')

def download_page(args=None):
    from neuron.plugins._util import open_website
    return open_website('https://www.blender.org/download/')

def focus(args=None):
    from neuron.plugins._util import focus
    return focus('Blender')

