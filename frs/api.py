import json
import logging
from contextlib import closing, contextmanager
from six.moves.urllib.request import urlopen

import six
import yaml
from jsonref import JsonRef
from flask import request, jsonify
from flask_restful import Api

from .errors import SwaggerError
from .validators import DefaultValidatingDraft4Validator


log = logging.getLogger(__name__)


class SwaggerApi(Api):
    TRUTHY = ('true', 't', 'yes', 'y', 'on', '1')
    FALSY = ('false', 'f', 'no', 'n', 'off', '0')

    def __init__(self, *args, **kwargs):
        self._config_prefix = kwargs.pop(
            'config_prefix', 'FRS')
        super(SwaggerApi, self).__init__(*args, **kwargs)

    def init_app(self, app, *args, **kwargs):
        self._config_prefix = kwargs.pop(
            'config_prefix', self._config_prefix)
        super(SwaggerApi, self).init_app(app, *args, **kwargs)

    def _init_app(self, app):
        self._spec_url = app.config.get(
            '{}_SPEC_URL'.format(self._config_prefix), None)
        self._resource_module = app.config.get(
            '{}_RESOURCE_MODULE'.format(self._config_prefix), None)
        self.validate_responses = self._asbool(app.config.get(
            '{}_VALIDATE_RESPONSES'.format(self._config_prefix), True))
        spec_text = self.get_spec_text()
        self.spec = yaml.load(spec_text)
        self._spec = JsonRef.replace_refs(self.spec)
        self._process_spec(self._spec)

        super(SwaggerApi, self)._init_app(app)

    def get_spec_text(self):
        with closing(urlopen(self._spec_url)) as fp:
            return fp.read()

    @contextmanager
    def path(self, path):
        yield _PathContext(self, path)

    def add_resource(self, resource, *urls, **kwargs):
        resource_class_args = tuple(kwargs.pop('resource_class_args', ()))
        resource_class_args = (self,) + resource_class_args
        kwargs['resource_class_args'] = resource_class_args
        return super(SwaggerApi, self).add_resource(resource, *urls, **kwargs)

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

    def _process_spec(self, spec):
        # Catalog the resources handling each path
        self._resource_paths = {}
        if self._resource_module:
            prefix = self._resource_module + '.'
        for path, pspec in spec['paths'].items():
            res = pspec.get('x-resource')
            if res:
                self._resource_paths[prefix + res] = pspec

    def _validate_response(self, resource, response):
        if not self.validate_responses:
            return
        method = request.method.lower()
        resp_spec = self._get_response(resource, method, response.status_code)
        if resp_spec is None:
            raise SwaggerError(
                500,
                json.loads(response.data),
                'Unknown response code {}'.format(
                    response.status_code))
        schema_spec = resp_spec.get('schema', None)
        if schema_spec is None:
            return
        schema = DefaultValidatingDraft4Validator(schema_spec)
        json_data = json.loads(response.data)
        schema.validate(json_data)

    def _validate_parameters(self, resource, args, kwargs):
        method = request.method.lower()
        params_spec = self._get_params(resource, method)

        params = {}

        # Check the body param
        body_param_spec = [p for p in params_spec if p['in'] == 'body']
        if body_param_spec:
            if request.content_type == 'application/json':
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
            if data is None:
                data = request.data
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

    def _get_params(self, resource, method):
        pspec = self._resource_paths.get(resource._resource_name(), {})
        ospec = pspec.get(method, {})
        params = pspec.get('parameters', []) + ospec.get('parameters', [])
        return params

    def _get_response(self, resource, method, status_code):
        pspec = self._resource_paths.get(resource._resource_name(), {})
        ospec = pspec.get(method, {})
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
            if param['required']:
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

        schema = DefaultValidatingDraft4Validator(schema_spec)
        schema.validate(res)
        return res

    def _check_body_param(self, param_spec, data):
        schema = DefaultValidatingDraft4Validator(param_spec['schema'])
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


class _PathContext(object):

    def __init__(self, api, path):
        self._api, self._path = api, path

    def add_resource(self, resource, *urls, **kwargs):
        if not urls:
            urls = ['']
        urls = [(self._path + u) for u in urls]
        return self._api.add_resource(resource, *urls, **kwargs)
