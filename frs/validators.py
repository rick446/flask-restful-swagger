import jsonschema


def extend_with_default(validator_class):
    validate_properties = validator_class.VALIDATORS["properties"]

    def set_defaults(validator, properties, instance, schema):
        for property, subschema in properties.iteritems():
            if "default" in subschema:
                instance.setdefault(property, subschema["default"])

        for error in validate_properties(
                validator, properties, instance, schema):
            yield error

    return jsonschema.validators.extend(
        validator_class, {"properties": set_defaults},
    )

DefaultValidatingDraft4Validator = extend_with_default(
    jsonschema.Draft4Validator)
