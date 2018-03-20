import inspect
from contextlib import contextmanager

from flask import request
from flask_restful import Resource
from werkzeug.wrappers import Response as ResponseBase

from jsonschema import SchemaError, ValidationError

from .errors import SwaggerError


class SwaggerResource(Resource):

    def __init__(self, api, *args, **kwargs):
        self.api = api
        super().__init__(*args, **kwargs)

    @classmethod
    def resource_name(cls):
        mod = inspect.getmodule(cls)
        return f'{mod.__name__}:{cls.__name__}'

    def dispatch_request(self, *args, **kwargs):
        with self.checking(400):
            request.swagger_params = self.api.validate_parameters(
                self, request, args, kwargs)

        response = super().dispatch_request(*args, **kwargs)
        if not isinstance(response, ResponseBase):
            return response
        if response.content_type != 'application/json':
            return response
        with self.checking(500):
            self.api.validate_response(self, request, response)
        return response

    @contextmanager
    def checking(self, code):
        try:
            yield
        except SwaggerError:
            raise
        except (SchemaError, ValidationError) as err:
            raise SwaggerError.from_jsonschema_error(code, err)
