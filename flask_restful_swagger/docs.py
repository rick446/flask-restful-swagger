from flask import jsonify, request, url_for, redirect, Response, send_from_directory

from flask import Blueprint
from flask import current_app as app
from flask_restful import Resource


mod = Blueprint(
    'docs', __name__,
    static_folder='static')


@mod.route('/')
def get_root():
    return redirect(url_for(
        '.get_static',
        filename='index.html',
        url=url_for('.get_swagger')))


@mod.route('/swagger.yaml')
def get_swagger():
    api = app.extensions['flask-restful-swagger']
    return Response(
        api.get_spec_text())


@mod.route('/static/<path:filename>')
def get_static(filename):
    import ipdb; ipdb.set_trace();
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

class Root(Resource):

    def __init__(self, api):
        self.api = api

    def get(self):
        import ipdb; ipdb.set_trace();
        return redirect('/_docs/static/index.html', url=url_for('spec')) # ?url=/_docs/swagger.yaml')


class Spec(Resource):

    def __init__(self, api):
        self.api = api

    def get(self):
        return Response(
            self.api.spec_text,
            headers={'Content-Type': 'application/x-yaml'})
