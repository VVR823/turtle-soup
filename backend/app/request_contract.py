"""Decode JSON without silently overwriting a player's duplicate fields."""
import json

from fastapi import Request
from fastapi.routing import APIRoute


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            # No raw input/key is included in a public validation error.
            # FastAPI treats decoder errors as validation failures (422), but
            # generic exceptions inside request.json() become an opaque 400.
            raise json.JSONDecodeError("Duplicate JSON field", "", 0)
        result[key] = value
    return result


class StrictJSONRequest(Request):
    async def json(self):
        if not hasattr(self, "_json"):
            self._json = json.loads(await self.body(), object_pairs_hook=_unique_object)
        return self._json


class StrictJSONRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def strict_request(request: Request):
            return await handler(StrictJSONRequest(request.scope, receive=request.receive))

        return strict_request
