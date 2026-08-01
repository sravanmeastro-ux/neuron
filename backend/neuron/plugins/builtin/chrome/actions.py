"""Builtin plugin actions: Chrome."""

def open(args=None):
    from neuron.plugins._util import open_app
    return open_app('Chrome')

def new_tab(args=None):
    args = args or {}
    url = str(args.get('url') or 'https://www.google.com')
    from neuron.plugins._util import open_app, open_website
    open_app('Chrome')
    return open_website(url)

def focus(args=None):
    from neuron.plugins._util import focus
    return focus('Chrome')

