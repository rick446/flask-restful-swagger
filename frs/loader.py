import jsonref
import yaml.dumper

try:
    import requests
except ImportError:
    requests = None

from six.moves.urllib import request, parse


class YamlLoader(jsonref.JsonLoader):

    def get_remote_json(self, uri, **kwargs):
        scheme = parse.urlsplit(uri).scheme

        if scheme in ["http", "https"] and requests:
            # Prefer requests, it has better encoding detection
            content = requests.get(uri).text
            result = yaml.load(content, **kwargs)
        else:
            # Otherwise, pass off to urllib and assume utf-8
            result = yaml.load(
                request.urlopen(uri).read().decode("utf-8"), **kwargs)

        return result


class YamlSafeDumper(yaml.dumper.SafeDumper):

    def __init__(self, *args, **kwargs):
        super(YamlSafeDumper, self).__init__(*args, **kwargs)
        self.add_representer(
            jsonref.JsonRef, yaml.dumper.SafeDumper.represent_dict)
