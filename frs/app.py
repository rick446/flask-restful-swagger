import os
import re
import logging
import importlib
from urllib.parse import urljoin
from pathlib import Path

from jinja2.nativetypes import NativeEnvironment
from jsonref import JsonRef
from jsonschema import validate
from flask import Blueprint

from .api import SwaggerApi
from .loader import YamlLoader
from .validators import DefaultValidatingDraft4Validator

log = logging.getLogger(__name__)
re_template_metacharacters = re.compile(r'({{)|({%)')


def mount_api(app, blueprint, spec, config, config_prefix=None, **kwargs):
    """'Magic' keys in spec:

    Global:
        - x-resource-base [None]: prefix for x-resource
        - x-validate-responses [False]: validate responses?
        - x-config-schema: JSONSchema for configuration data

    Per path:
        - x-resource: the resource to mount at the given path
    """
    name = spec['x-resource-base']
    if name.endswith('.'):
        name = name[:-1]
    if config_prefix is None:
        config_prefix = name
    # Validate config from spec
    config_schema = spec.get('x-config-schema', None)
    if config_schema:
        schema = DefaultValidatingDraft4Validator(config_schema)
        schema.validate(config)
    log.debug('Mounting API %s (config => %s)', name, config_prefix)
    mod = importlib.import_module(name)
    api = SwaggerApi(spec, blueprint, **kwargs)
    api.config = config
    api._config_prefix = config_prefix
    for k, v in config.items():
        app.config[f'{config_prefix}_{k}'] = v
    app.register_blueprint(blueprint)
    return api


def load_spec(spec_uri, base_uri=None):
    if base_uri:
        spec_uri = urljoin(base_uri, spec_uri)
    loader = YamlLoader()
    spec = JsonRef({'$ref': spec_uri}, loader=loader)
    exp = TemplateExpander(spec_uri)
    spec = exp(spec)
    spec = JsonRef.replace_refs(spec, base_uri=spec_uri, loader=loader)
    return spec


class TemplateExpander(object):
    """Object to expand templates found as strings in structured data
    """

    def __init__(self, base_uri):
        self.ctx = {
            'env': os.environ,
            'load_spec': lambda uri: load_spec(uri, base_uri)
        }
        self.env = NativeEnvironment()

    def __call__(self, node, seen=None):
        if seen is None:
            seen = {}
        if id(node) in seen:
            return node
        elif isinstance(node, list):
            return [self(n, seen) for n in node]
        elif isinstance(node, dict):
            return {
                self(k, seen): self(v, seen)
                for k, v in node.items()
            }
        elif isinstance(node, str):
            if re_template_metacharacters.search(node):
                t = self.env.from_string(node)
                return t.render(self.ctx)
            else:
                return node
        return node


def expland_template(node, env, ctx, seen=None):
    if seen is None:
        seen = {}
    if id(node) in seen:
        return node
    elif isinstance(node, list):
        return [expland_template(n, env, ctx, seen) for n in node]
    elif isinstance(node, dict):
        return {
            expland_template(k, env, ctx, seen): expland_template(v, env, ctx, seen)
            for k, v in node.items()
        }
    elif isinstance(node, str):
        t = env.from_string(node)
        # t = Template(node, variable_start_string='<<', variable_end_string='>>')
        if node == "<<load_spec('./oauth.yaml#dev')>>":
            print(node)
            import pdb; pdb.set_trace();
        return t.render(ctx)
    return node
