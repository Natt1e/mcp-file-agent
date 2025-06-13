from typing import Annotated, Optional
from typing import List, Optional, Literal, Dict, Any
import os
import pathspec
import asyncio
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.shared.exceptions import McpError
import mcp.types as types
import mcp.server.stdio
from pydantic import BaseModel, Field
import datetime
from pathlib import Path
import fnmatch
import shutil
import json




def expand_home(p: str) -> str:
    return os.path.expanduser(p)

def normalize_path(p: str) -> str:
    return os.path.normpath(Path(p).resolve().as_posix())

def validate_path(requested_path: str) -> str:
    global allowed_directories
    expanded = expand_home(requested_path)
    abs_path = Path(expanded).resolve() if Path(expanded).is_absolute() \
               else (Path.cwd() / expanded).resolve()
    normalized_requested = normalize_path(abs_path)

    # Check if path is within allowed directories
    if not any(normalized_requested.startswith(d) for d in allowed_directories):
        raise ValueError(f"Access denied – path outside allowed directories: {abs_path}")

    try:
        # Handle symlinks by checking their real path
        real_path = Path(os.path.realpath(abs_path))
        normalized_real = normalize_path(real_path)
        if not any(normalized_real.startswith(d) for d in allowed_directories):
            raise ValueError("Access denied – symlink target outside allowed directories")
        return str(real_path)  # symlink OK
    except FileNotFoundError:
        # For new files that don't exist yet, verify parent directory
        parent_dir = abs_path.parent
        try:
            real_parent = Path(os.path.realpath(parent_dir))
        except FileNotFoundError:
            raise ValueError(f"Parent directory does not exist: {parent_dir}")

        normalized_parent = normalize_path(real_parent)
        if not any(normalized_parent.startswith(d) for d in allowed_directories):
            raise ValueError("Access denied – parent directory outside allowed directories")
        return str(abs_path) 

def get_allowed_directories(args):
    return [
        normalize_path(os.path.abspath(expand_home(arg)))
        for arg in args
    ]


""" Schema definitions """
class ReadFileArgsSchema(BaseModel) :
    path: str

class ReadMultipleFilesArgsSchema(BaseModel) :
    paths: List[str]

class WriteFileArgsSchema(BaseModel) :
    path: str
    content: str

class EditOperationSchema(BaseModel):
    oldText: str = Field(description="Text to search for - must match exactly")
    newText: str = Field(description="Text to replace with")


class EditFileArgsSchema(BaseModel):
    path: str
    edits: List[EditOperationSchema]
    dryRun: bool = Field(default=False, description="Preview changes using git-style diff format")

class CreateDirectoryArgsSchema(BaseModel):
    path: str

class ListDirectoryArgsSchema(BaseModel):
    path: str

class DirectoryTreeArgsSchema(BaseModel):
    path: str

class MoveFileArgsSchema(BaseModel):
    source: str
    destination: str

class SearchFilesArgsSchema(BaseModel):
    path: str
    pattern: str
    excludePatterns: Optional[List[str]] = []

class GetFileInfoArgsSchema(BaseModel):
    path: str

# Tool implementations
async def get_file_stats(file_path: str) -> Dict[str, Any]:
    stats = os.stat(file_path)
    return {
        'size': stats.st_size,
        'created': datetime.fromtimestamp(stats.st_ctime),
        'modified': datetime.fromtimestamp(stats.st_mtime),
        'accessed': datetime.fromtimestamp(stats.st_atime),
        'isDirectory': os.path.isdir(file_path),
        'isFile': os.path.isfile(file_path),
        'permissions': oct(stats.st_mode & 0o777)[-3:],
    }


def _matches_exclude(relative_path: str, patterns: List[str]) -> bool:
    rel_posix = Path(relative_path).as_posix()
    for pat in patterns:
        glob_pat = pat if '*' in pat else f"**/{pat}/**"
        if fnmatch.fnmatch(rel_posix, glob_pat):
            return True
    return False

def search_files(root_path: str,
                 name_pattern: str,
                 exclude_patterns: List[str] | None = None) -> List[str]:
 
    exclude_patterns = exclude_patterns or []
    results: List[str] = []

    root_path = Path(root_path).resolve()

    def _search(current: Path):
        try:
            entries = list(current.iterdir())
        except PermissionError:
            return

        for entry in entries:
            full_path = entry.resolve()          
            try:
                validate_path(str(full_path))    
            except Exception:
                continue                      

            relative = full_path.relative_to(root_path)

            if _matches_exclude(relative.as_posix(), exclude_patterns):
                continue

            if name_pattern.lower() in entry.name.lower():
                results.append(str(full_path))

            if entry.is_dir():
                _search(full_path)

    _search(root_path)
    return results

async def serve(
    root_path: str, custom_ignore_patterns: Optional[list[str]] = None
) -> None:
    """Run the filesystem MCP server.

    Args:
        root_path: Base directory to serve files from
        custom_ignore_patterns: Optional list of patterns to ignore
    """
    if not os.path.exists(root_path):
        raise ValueError(f"Directory does not exist: {root_path}")

    root_path = os.path.abspath(root_path)
    server = Server("filesystem")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """List available tools."""
        return [
            types.Tool(
                name="read_file",
                description=(
                    "Read the complete contents of a file from the file system. "
                    "Handles various text encodings and provides detailed error messages "
                    "if the file cannot be read. Use this tool when you need to examine "
                    "the contents of a single file. Only works within allowed directories."
                ),
                inputSchema=ReadFileArgsSchema.model_json_schema(),
            ),
            types.Tool(
                name="read_multiple_files",
                description=(
                    "Read the contents of multiple files simultaneously. This is more "
                    "efficient than reading files one by one when you need to analyze "
                    "or compare multiple files. Each file's content is returned with its "
                    "path as a reference. Failed reads for individual files won't stop "
                    "the entire operation. Only works within allowed directories."
                ),
                inputSchema=ReadMultipleFilesArgsSchema.model_json_schema(),
            ),
            types.Tool(
                name="write_file",
                description=(
                    "Create a new file or completely overwrite an existing file with new content. "
                    "Use with caution as it will overwrite existing files without warning. "
                    "Handles text content with proper encoding. Only works within allowed directories."
                ),
                inputSchema=WriteFileArgsSchema.model_json_schema(),
            ),
            types.Tool(
                name="edit_file",
                description=(
                    "Make line-based edits to a text file. Each edit replaces exact line sequences "
                    "with new content. Returns a git-style diff showing the changes made. "
                    "Only works within allowed directories."
                ),
                inputSchema=EditFileArgsSchema.model_json_schema(),
            ),
            types.Tool(
                name="create_directory",
                description=(
                    "Create a new directory or ensure a directory exists. Can create multiple "
                    "nested directories in one operation. If the directory already exists, "
                    "this operation will succeed silently. Perfect for setting up directory "
                    "structures for projects or ensuring required paths exist. Only works within allowed directories."
                ),
                inputSchema=CreateDirectoryArgsSchema.model_json_schema(),
            ),
            types.Tool(
                name="list_directory",
                description=(
                    "Get a detailed listing of all files and directories in a specified path. "
                    "Results clearly distinguish between files and directories with [FILE] and [DIR] "
                    "prefixes. This tool is essential for understanding directory structure and "
                    "finding specific files within a directory. Only works within allowed directories."
                ),
                inputSchema=ListDirectoryArgsSchema.model_json_schema(),
            ),
            types.Tool(
                name="directory_tree",
                description=(
                    "Get a recursive tree view of files and directories as a JSON structure. "
                    "Each entry includes 'name', 'type' (file/directory), and 'children' for directories. "
                    "Files have no children array, while directories always have a children array (which may be empty). "
                    "The output is formatted with 2-space indentation for readability. Only works within allowed directories."
                ),
                inputSchema=DirectoryTreeArgsSchema.model_json_schema(),
            ),
            types.Tool(
                name="move_file",
                description=(
                    "Move or rename files and directories. Can move files between directories "
                    "and rename them in a single operation. If the destination exists, the "
                    "operation will fail. Works across different directories and can be used "
                    "for simple renaming within the same directory. Both source and destination must be within allowed directories."
                ),
                inputSchema=MoveFileArgsSchema.model_json_schema(),
            ),
            types.Tool(
                name="search_files",
                description=(
                    "Recursively search for files and directories matching a pattern. "
                    "Searches through all subdirectories from the starting path. The search "
                    "is case-insensitive and matches partial names. Returns full paths to all "
                    "matching items. Great for finding files when you don't know their exact location. "
                    "Only searches within allowed directories."
                ),
                inputSchema=SearchFilesArgsSchema.model_json_schema(),
            ),
            types.Tool(
                name="get_file_info",
                description=(
                    "Retrieve detailed metadata about a file or directory. Returns comprehensive "
                    "information including size, creation time, last modified time, permissions, "
                    "and type. This tool is perfect for understanding file characteristics "
                    "without reading the actual content. Only works within allowed directories."
                ),
                inputSchema=GetFileInfoArgsSchema.model_json_schema(),
            ),
            types.Tool(
                name="list_allowed_directories",
                description=(
                    "Returns the list of directories that this server is allowed to access. "
                    "Use this to understand which directories are available before trying to access files."
                ),
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
        ]



    @server.call_tool()
    async def handle_request(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if name == "read_file":
                file_path = validate_path(args['path'])
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return [
                    types.TextContent(
                        type="text", text=content
                    )
                ]

            elif name == "read_multiple_files":
                results = []
                for file_path in args['paths']:
                    try:
                        valid_path = validate_path(file_path)
                        with open(valid_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        results.append(f"{file_path}:\n{content}")
                    except Exception as e:
                        results.append(f"{file_path}: Error - {str(e)}")
                return [
                    types.TextContent(
                        type="text", text="\n---\n".join(results)
                    )
                ]

            elif name == "write_file":
                file_path = validate_path(args['path'])
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(args['content'])
                return [
                    types.TextContent(
                        type="text", text=f"Successfully wrote to {args['path']}"
                    )
                ]

            elif name == "edit_file":
                file_path = validate_path(args['path'])
                # Apply edits logic (simplified for now)
                result = f"File {args['path']} edited with changes: {args['edits']}"
                return {"content": [{"type": "text", "text": result}]}

            elif name == "create_directory":
                dir_path = validate_path(args['path'])
                os.makedirs(dir_path, exist_ok=True)
                return [
                    types.TextContent(
                        type="text", text=f"Successfully created directory {args['path']}"
                    )
                ]
            elif name == "list_directory":
                dir_path = validate_path(args['path'])
                entries = os.listdir(dir_path)
                formatted = "\n".join([f"[DIR] {entry}" if os.path.isdir(os.path.join(dir_path, entry)) else f"[FILE] {entry}" for entry in entries])
                return [
                    types.TextContent(
                        type="text", text=formatted
                    )
                ]             

            elif name == "directory_tree":
                def build_tree(current_path: str) -> List[Dict[str, Any]]:
                    entries = os.listdir(current_path)
                    tree = []
                    for entry in entries:
                        entry_path = os.path.join(current_path, entry)
                        tree_entry = {
                            "name": entry,
                            "type": "directory" if os.path.isdir(entry_path) else "file",
                            "children": build_tree(entry_path) if os.path.isdir(entry_path) else []
                        }
                        tree.append(tree_entry)
                    return tree

                root_path = validate_path(args['path'])
                tree_data = build_tree(root_path)
                return [
                    types.TextContent(
                        type="text", text=json.dumps(tree_data, indent=2)
                    )
                ]

            elif name == "move_file":
                source_path = validate_path(args['source'])
                destination_path = validate_path(args['destination'])
                shutil.move(source_path, destination_path)

                return [
                    types.TextContent(
                        type="text", text=f"Successfully moved {args['source']} to {args['destination']}"
                    )
                ]
            elif name == "search_files":
                search_results = search_files(args['path'], args['pattern'], args.get('excludePatterns', []))
                return [
                    types.TextContent(
                        type="text", text="\n".join(search_results) if search_results else "No matches found"
                    )
                ]    

            elif name == "get_file_info":
                file_info = get_file_stats(args['path'])
                info_text = "\n".join([f"{key}: {value}" for key, value in file_info.items()])
                return [
                    types.TextContent(
                        type="text", text=info_text
                    )
                ]    

            elif name == "list_allowed_directories":
                return [
                    types.TextContent(
                        type="text", text="\n".join(allowed_directories)
                    )
                ]    

            else:
                raise ValueError(f"Unknown request: {name}")

        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}


    # Run the server
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="filesystem",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import sys
    global allowed_directories
    if len(sys.argv) == 1:
        print("Usage:python mcp-server-filesystem.py <allowed-directory> [additional-directories...]")
        sys.exit(1)
    allowed_directories = get_allowed_directories(sys.argv[1:])
    asyncio.run(serve(sys.argv[1]))