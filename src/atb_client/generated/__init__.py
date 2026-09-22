"""Models generated from the server's ``/api/v1/openapi.json``.

Empty until the v1 server publishes its schema. ``scripts/generate_models.sh <url>``
writes ``models.py`` here with ``datamodel-codegen``; the CI ``contract`` job regenerates
it against the deployed schema and fails on any diff. When it lands,
:mod:`atb_client.models` switches its hand-written classes to subclasses of these,
keeping only the behaviour (``wait()``, ``files``, pagination) it layers on top.
"""
