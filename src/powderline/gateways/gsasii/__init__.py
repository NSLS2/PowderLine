"""GSAS-II gateway package.

Do not import runtime modules (setters, project, executors, extractors, ...)
here: they import GSAS-II at module top. The engine-free gateway factory
(the ``powderline.gateways`` entry point) is ``gateways/gsasii/gateway.py``.
"""
