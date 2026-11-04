"""Local stdio MCP. SDK imports are optional and never occur on core import."""
from .api import FeedbackApp, operation_definitions
from .contracts import FeedbackError, canonical_json
from .store import FeedbackStore


def serve(project):
    try:
        import asyncio
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations
    except ImportError:
        raise FeedbackError("MCP_NOT_INSTALLED", "Install Tradeoff with its mcp extra to use local MCP") from None
    with FeedbackStore(project):
        pass
    app = FeedbackApp(project)
    definitions = operation_definitions()
    names = {"tradeoff_" + d["operation"]: d["operation"] for d in definitions}

    async def list_tools(ctx, params):
        return ListToolsResult(tools=[Tool(name="tradeoff_" + d["operation"], description=d["description"],
            input_schema=d["input_schema"], annotations=ToolAnnotations(**d["annotations"])) for d in definitions])

    async def call_tool(ctx, params):
        try:
            if params.name not in names:
                raise FeedbackError("UNKNOWN_TOOL", "Unknown feedback operation")
            payload = await asyncio.to_thread(app.dispatch, names[params.name], params.arguments)
            return CallToolResult(content=[TextContent(type="text", text=canonical_json(payload))], structured_content=payload)
        except FeedbackError as exc:
            error = {"status": "ERROR", "error": {"code": exc.code, "message": exc.message}}
        except Exception:
            error = {"status": "ERROR", "error": {"code": "INTERNAL_ERROR", "message": "Feedback tool request failed"}}
        return CallToolResult(content=[TextContent(type="text", text=canonical_json(error))], structured_content=error, is_error=True)

    async def run():
        server = Server("Tradeoff", version="1", on_list_tools=list_tools, on_call_tool=call_tool)
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())
    asyncio.run(run())
