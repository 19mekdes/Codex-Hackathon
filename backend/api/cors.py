from django.http import HttpResponse


ALLOWED_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


class LocalFrontendCorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get("Origin")
        response = HttpResponse(status=204) if request.method == "OPTIONS" else self.get_response(request)
        if origin in ALLOWED_ORIGINS:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type"
            response["Vary"] = "Origin"
        return response
