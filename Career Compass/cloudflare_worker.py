import os
from urllib.parse import quote, urlsplit

os.environ["CLOUDFLARE_WORKERS"] = "1"

from flask import request
from jinja2 import BaseLoader, TemplateNotFound
from js import Request
from pyodide.ffi import run_sync
from workers import WorkerEntrypoint, wsgi

from app import app, career_by_id
from career_market import current_model_api_key, refresh_stale_insights


class CloudflareTemplateLoader(BaseLoader):
    def get_source(self, environment, template):
        if template.startswith("/") or ".." in template.split("/"):
            raise TemplateNotFound(template)

        worker_environment = request.environ["workers.env"]
        template_url = (
            f"{request.scheme}://{request.host}/templates/"
            f"{quote(template, safe='/')}"
        )
        response = run_sync(
            worker_environment.ASSETS.fetch(Request.new(template_url))
        )
        if not response.ok:
            raise TemplateNotFound(template)

        source = run_sync(response.text())
        return source, template_url, lambda: True


class SecretKeyMiddleware:
    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        secret = str(environ["workers.env"].SECRET_KEY)
        if len(secret) < 32 or secret in ("undefined", "None"):
            raise RuntimeError("Set a 32-character or longer SECRET_KEY Worker secret.")

        app.config["SECRET_KEY"] = secret
        app.config["SESSION_COOKIE_SECURE"] = True
        return self.application(environ, start_response)


app.jinja_loader = CloudflareTemplateLoader()


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        if urlsplit(str(request.url)).path.startswith("/static/"):
            return await self.env.ASSETS.fetch(request)
        return await wsgi.fetch(SecretKeyMiddleware(app), request, self.env)

    async def scheduled(self, controller, env, ctx):
        api_key = current_model_api_key(env)
        if not api_key:
            print("Career insight refresh skipped: MODEL_API_KEY is not configured.")
            return

        from cloudflare_d1 import D1Database

        refreshed = refresh_stale_insights(
            D1Database(env.DB),
            api_key,
            career_by_id,
            worker_environment=env,
        )
        print(f"Career insight refresh completed: {refreshed} reports refreshed.")
