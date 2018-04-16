import cgi
import json
import yaml
import logging
import importlib

import six
from flask import jsonify
from flask_restful import Api

from .loader import YamlSafeDumper
from .errors import SwaggerError
from .validators import DefaultValidatingDraft4Validator


log = logging.getLogger(__name__)


def flask_from_swagger(path):
    return path.replace('{', '<').replace('}', '>')


def swagger_from_flask(path):
    return path.replace('<', '{').replace('>', '}')


class SwaggerApi(Api):
    TRUTHY = ('true', 't', 'yes', 'y', 'on', '1')
    FALSY = ('false', 'f', 'no', 'n', 'off', '0')

    def __init__(self, spec, *args, **kwargs):
        self._Validator = kwargs.pop(
            'validator', DefaultValidatingDraft4Validator)
        self._resource_paths = {}
        self._spec = spec
        self._resource_map = {}
        super().__init__(*args, **kwargs)

    def _init_app(self, app):
        for path, pspec in self._spec['paths'].items():
            resource_path = pspec.get('x-resource')
            if resource_path is None:
                log.debug('Ignoring un-resourced path %s', path)
                continue
            resource_class = self._load_resource(resource_path)
            urls = [path]
            if path.endswith('/') and not self.strict_trailing_slash:
                urls.append(path[:-1])
            self.add_resource(resource_class, *urls, pathspec=pspec)
        super(SwaggerApi, self)._init_app(app)

    def get_spec_json(self):
        return json.dumps(self._spec, default=dict, indent=4)

    def get_spec_yaml(self):
        return yaml.dump(self._spec, Dumper=YamlSafeDumper)

    @property
    def basePath(self):
        return self._spec.get('basePath', '')

    @property
    def strict_trailing_slash(self):
        return self._spec.get('x-strict-trailing_slash', False)

    @property
    def resource_base(self):
        return self._spec.get('x-resource-base', None)

    @property
    def validate_responses(self):
        return self._spec.get('x-validate-responses', False)

    def validate_parameters(self, resource, request, args, kwargs):
        pathspec = self._get_pathspec(resource)
        params_spec = self._get_params(pathspec, request.method.lower())

        params = {}

        # Check the body param
        body_param_spec = [p for p in params_spec if p['in'] == 'body']
        if body_param_spec:
            content_type = cgi.parse_header(request.content_type)[0]
            if content_type == 'application/json':
                try:
                    data = request.json
                except Exception as err:
                    log.warning(
                        "Client said it sent JSON, but it didn't: %r",
                        request.data)
                    data = None
            elif request.content_type in (
                    'application/x-www-form-urlencoded',
                    'multipart/form-data'):
                data = request.form
            else:
                data = None
            if data is not None:
                params['body'] = self._check_body_param(
                    body_param_spec[0], data)

        # Check the primitive params
        params.update(self._check_primitive_params(
            params_spec, 'path', kwargs))
        params.update(self._check_primitive_params(
            params_spec, 'query', request.args))
        params.update(self._check_primitive_params(
            params_spec, 'header', request.headers))
        params.update(self._check_primitive_params(
            params_spec, 'form', request.form))
        return params

    def validate_response(self, resource, request, response):
        if not self._spec.get('x-validate-responses', False):
            return
        method = request.method.lower()
        pathspec = self._get_pathspec(resource)

        resp_spec = self._get_response(pathspec, method, response.status_code)
        if resp_spec is None:
            raise SwaggerError(
                500,
                json.loads(response.data),
                'Unknown response code {}'.format(
                    response.status_code))
        schema_spec = resp_spec.get('schema', None)
        if schema_spec is None:
            return
        schema = self._Validator(schema_spec)
        json_data = json.loads(response.data)
        schema.validate(json_data)

    def add_resource(self, resource, *swagger_paths, **kwargs):
        pathspec = kwargs.pop('pathspec', None)
        if pathspec:
            self._resource_map[resource.resource_name()] = pathspec
        swagger_paths = [
            self._spec.get('basePath', '') + u for u in swagger_paths]
        urls = [flask_from_swagger(path) for path in swagger_paths]
        log.debug('Mount %r at %r', resource, urls)
        resource_class_args = tuple(kwargs.pop('resource_class_args', ()))
        resource_class_args = (self,) + resource_class_args
        return super().add_resource(
            resource, *urls, resource_class_args=resource_class_args, **kwargs)

    def handle_invalid_usage(self, error):
        response = jsonify(dict(
            errors=error.errors,
            value=error.value))
        response.status_code = error.status_code
        return response

    def handle_error(self, e):
        if isinstance(e, SwaggerError):
            return self.handle_invalid_usage(e)
        return super(SwaggerApi, self).handle_error(e)

    def _load_resource(self, resource_module_path):
        full_path = self._spec['x-resource-base'] + resource_module_path
        modname, classname = full_path.split(':')
        mod = importlib.import_module(modname)
        return getattr(mod, classname)

    def _get_pathspec(self, resource):
        return self._resource_map[resource.resource_name()]

    def _get_params(self, pathspec, method):
        ospec = pathspec.get(method, {})
        params = pathspec.get('parameters', []) + ospec.get('parameters', [])
        return params

    def _get_response(self, pathspec, method, status_code):
        ospec = pathspec.get(method, {})
        responses = ospec.get('responses', {})
        return responses.get(str(status_code), None)

    def _check_primitive_params(self, params_spec, ptype, data):
        """Validate and convert parameters of a certain primitive type.

        This will verify that *data* correctly validates, and will return
        the validated and converted data.

        Valid ptypes:
         - path
         - query
         - header
         - form
        """
        schema_spec = dict(
            type='object',
            properties={},
            required=[])

        res = dict(data)

        for param in params_spec:
            if param['in'] != ptype:
                continue
            p_name = param['name']
            p_type = param['type']
            p_format = param.get('format', None)
            if param.get('required', False):
                schema_spec['required'].append(p_name)
            schema_spec['properties'][p_name] = p_sch = dict(type=p_type)
            if p_format:
                p_sch['format'] = p_format
            if 'default' in param:
                p_sch['default'] = param['default']

            try:
                value = data[p_name]
            except KeyError:
                continue

            # Attempt primitive type conversion
            if p_type == 'integer':
                try:
                    res[p_name] = int(value)
                except:
                    pass
            elif p_type == 'number':
                try:
                    res[p_name] = float(value)
                except:
                    pass
            elif p_type == 'boolean':
                res[p_name] = self._asbool(value)
            elif p_type == 'string':
                res[p_name] = six.text_type(value)

        schema = self._Validator(schema_spec)
        schema.validate(res)
        return res

    def _check_body_param(self, param_spec, data):
        if 'schema' in param_spec:
            schema = self._Validator(param_spec['schema'])
        else:
            schema = self._Validator(param_spec)
        schema.validate(data)
        return data

    def _asbool(self, value):
        if not isinstance(value, six.string_types):
            return value
        if value.lower() in self.TRUTHY:
            return True
        elif value.lower() in self.FALSY:
            return False
        else:
            return value
