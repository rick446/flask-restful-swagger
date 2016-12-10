from itertools import chain
from collections import defaultdict

from .validators import DefaultValidatingDraft4Validator


class SwaggerError(Exception):

    def __init__(self, status_code, value, errors):
        super(SwaggerError, self).__init__()
        self.status_code = status_code
        self.value = value
        self.errors = errors

    @classmethod
    def from_jsonschema_error(cls, status_code, err):
        schema = DefaultValidatingDraft4Validator(err.schema)
        instance = err.instance
        errors = defaultdict(list)
        for e in schema.iter_errors(instance):
            path = '.'.join(str(p) for p in chain(err.path, e.path))
            errors[path].append(e.message)
        self = cls(status_code, instance, errors)
        return self
