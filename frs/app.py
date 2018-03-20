import os
import logging
import importlib
from pathlib import Path

from jinja2 import Template
from jsonref import JsonRef
from flask import Blueprint

from .api import SwaggerApi
from .loader import YamlLoader

log = logging.getLogger(__name__)


def mount_api(app, spec, config_prefix=None):
    """'Magic' keys in spec:

    Global:
        - x-resource-base [None]: prefix for x-resource
        - x-validate-responses [False]: validate responses?
        - x-extra: extra, arbitrary API configuration

    Per path:
        - x-resource: the resource to mount at the given path
    """
    name = spec['x-resource-base']
    if config_prefix is None:
        config_prefix = name
    log.debug('Mounting API %s (config => %s)', name, config_prefix)
    mod = importlib.import_module(name)
    bp = Blueprint(name, mod.__name__)
    api = SwaggerApi(spec, bp)
    for k, v in api.extra_config.items():
        app.config[f'{config_prefix}_{k}'] = v
    app.register_blueprint(bp)
    return api


def load_spec(spec_path_or_uri):
    if isinstance(spec_path_or_uri, Path):
        spec_uri = spec_path_or_uri.resolve().as_uri()
    elif '://' in spec_path_or_uri:
        spec_uri = spec_path_or_uri
    else:
        spec_uri = Path(spec_path_or_uri).resolve().as_uri()
    loader = YamlLoader()
    spec = loader.get_remote_json(spec_uri)
    spec = replace_environ_vars(spec)
    spec = JsonRef.replace_refs(spec, base_uri=spec_uri, loader=loader)
    spec = replace_environ_vars(spec)
    return spec


def replace_environ_vars(node, seen=None):
    if seen is None:
        seen = {}
    if id(node) in seen:
        return node
    elif isinstance(node, list):
        return [replace_environ_vars(n, seen) for n in node]
    elif isinstance(node, dict):
        return {
            replace_environ_vars(k, seen): replace_environ_vars(v, seen)
            for k, v in node.items()
        }
    elif isinstance(node, str):
        t = Template(node)
        return t.render(os.environ)
    return node
