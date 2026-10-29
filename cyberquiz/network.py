"""Reuse HTTPS connections per thread; no shared mutable session state."""
import threading
import requests

_local=threading.local()


def http():
    if not hasattr(_local,'session'):_local.session=requests.Session()
    return _local.session
