"""
Backward-compatibility alias forwarding to server.py.
"""
import sys
import server

sys.modules[__name__] = server
