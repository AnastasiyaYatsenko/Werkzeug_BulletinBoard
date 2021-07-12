"""A simple URL shortener using Werkzeug and redis."""
import os

import redis
from jinja2 import Environment
from jinja2 import FileSystemLoader
import json
from werkzeug.exceptions import HTTPException
from werkzeug.exceptions import NotFound
from werkzeug.middleware.shared_data import SharedDataMiddleware
from werkzeug.routing import Map
from werkzeug.routing import Rule
from werkzeug.urls import url_parse
from werkzeug.utils import redirect
from werkzeug.wrappers import Request
from werkzeug.wrappers import Response

from datetime import datetime
from collections import OrderedDict


def get_hostname(url):
    return url_parse(url).netloc


class BulletinBoard:
    def __init__(self, config):
        self.redis = redis.StrictRedis(config["redis_host"], config["redis_port"], charset="utf-8", decode_responses=True)

        template_path = os.path.join(os.path.dirname(__file__), "templates")
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_path), autoescape=True
        )
        self.jinja_env.filters["hostname"] = get_hostname

        self.url_map = Map(
            [
                Rule("/", endpoint="home"),
                Rule("/new", endpoint="new_ad"),
                Rule("/ad_<short_id>", endpoint="ad"),
            ]
        )

    def on_home(self, request):
        megaobj = {}
        for key in self.redis.scan_iter():
            megaobj[key] = json.loads(self.redis.get(key))
        sortedlist = OrderedDict(sorted(megaobj.items(), key=lambda t: t[0], reverse=True))
        return self.render_template("home.html", ads=sortedlist)

    def on_ad(self, request, short_id):
        link_target = self.redis.get(short_id)
        if link_target is None:
            raise NotFound()
        if request.method == "POST":
            comment_author = request.form["comment_author"]
            comment_text = request.form["comment_text"]
            self.insert_comment(comment_author, comment_text, short_id)
        megaobj = json.loads(self.redis.get(short_id))
        return self.render_template("ad_detailed.html", ad=megaobj)

    def on_new_ad(self, request):
        if request.method == "POST":
            ad_author = request.form["ad_author"]
            title = request.form["title"]
            ad_text = request.form["ad_text"]
            self.insert_ad(ad_author, title, ad_text)
        return self.render_template("new_ad.html")

    def error_404(self):
        response = self.render_template("404.html")
        response.status_code = 404
        return response

    def insert_ad(self, author, title, text):
        now = datetime.now()
        short_id = (now - datetime(1970, 1, 1)).total_seconds()
        while self.redis.get(str(short_id)) is not None:
            short_id =+ 1
        str_now = now.strftime("%d/%m/%Y %H:%M")
        ad = f'"author": "{author}", "theme": "{title}", "text": "{text}", "date": "{str_now}", "comments":[]'
        self.redis.set(f"{str(short_id)}", "{"+ad+"}")
        return str(short_id)

    def insert_comment(self, author, text, short_id):
        now = datetime.now()
        str_now = now.strftime("%d/%m/%Y %H:%M")
        comment = {"author": author, "text": text, "date": str_now}
        upd_ad = json.loads(self.redis.get(short_id))
        upd_ad["comments"].append(comment)
        str_ad = json.dumps(upd_ad)
        self.redis.set(f"{short_id}", str_ad)
        return short_id

    def render_template(self, template_name, **context):
        t = self.jinja_env.get_template(template_name)
        return Response(t.render(context), mimetype="text/html")

    def dispatch_request(self, request):
        adapter = self.url_map.bind_to_environ(request.environ)
        try:
            endpoint, values = adapter.match()
            return getattr(self, f"on_{endpoint}")(request, **values)
        except NotFound:
            return self.error_404()
        except HTTPException as e:
            return e

    def wsgi_app(self, environ, start_response):
        request = Request(environ)
        response = self.dispatch_request(request)
        return response(environ, start_response)

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)


def create_app(redis_host="localhost", redis_port=6379, with_static=True):
    app = BulletinBoard({"redis_host": redis_host, "redis_port": redis_port})
    if with_static:
        app.wsgi_app = SharedDataMiddleware(
            app.wsgi_app, {"/static": os.path.join(os.path.dirname(__file__), "static")}
        )
    return app


if __name__ == "__main__":
    from werkzeug.serving import run_simple

    app = create_app()
    run_simple("127.0.0.1", 5000, app, use_debugger=True, use_reloader=True)
