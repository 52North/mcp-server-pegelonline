"""Tool annotations shared by the tool modules."""

from mcp.types import ToolAnnotations

# Every tool only reads, and all of them query the external Pegelonline APIs;
# clients may run them without asking for confirmation.
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
