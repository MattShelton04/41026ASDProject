"""Visual regression captures, pixel comparison, galleries and trusted publication.

Capture (``capture.py``) drives a browser and is the only module that imports Playwright. Every
other module is used by the trusted publisher, which installs only the ``visual`` dependency group
(Pillow and NumPy) from the default branch's lockfile.
"""
