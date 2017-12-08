from flask import url_for, redirect, Response

from flask import Blueprint


def make_blueprint(api):
    bp = Blueprint(api._config_prefix, __name__, static_folder='static')

    @bp.route('/')
    def get_root():
        return redirect(url_for(
            '.static',
            filename='index.html',
            url=url_for('.get_swagger')))

    @bp.route('/swagger.json')
    def get_swagger():
        return Response(
            api.get_spec_json(),
            mimetype='application/json')

    @bp.route('/swagger.yaml')
    def get_swagger_yaml():
        return Response(
            api.get_spec_yaml(),
            mimetype='text/x-yaml')

    return bp
