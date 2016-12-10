import inspect
from contextlib import contextmanager

from flask import request
from flask_restful import Resource
from werkzeug.wrappers import Response as ResponseBase

from jsonschema import SchemaError, ValidationError

from .errors import SwaggerError


class SwaggerResource(Resource):

    def __init__(self, api, *args, **kwargs):
        self._api = api
        super(SwaggerResource, self).__init__(*args, **kwargs)

    def _resource_name(self):
        cls = self.__class__
        mod = inspect.getmodule(cls)
        return '{}:{}'.format(mod.__name__, cls.__name__)

    def dispatch_request(self, *args, **kwargs):
        with self.checking(400):
            request.swagger_params = self._api._validate_parameters(
                self, args, kwargs)

        resp = super(SwaggerResource, self).dispatch_request(*args, **kwargs)
        if not isinstance(resp, ResponseBase):
            return resp
        if resp.content_type != 'application/json':
            return resp
        with self.checking(500):
            self._api._validate_response(self, resp)
        return resp

    @contextmanager
    def checking(self, code):
        try:
            yield
        except SwaggerError:
            raise
        except (SchemaError, ValidationError) as err:
            raise SwaggerError.from_jsonschema_error(code, err)

