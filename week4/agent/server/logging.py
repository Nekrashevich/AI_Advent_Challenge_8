import logging


def configure_mcp_tool_logging():
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
