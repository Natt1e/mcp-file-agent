import asyncio
import os
import json
import sys
from typing import Optional
from contextlib import AsyncExitStack
from openai import OpenAI
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()


class MCPClient:
    def __init__(self):
        self.exit_stack = AsyncExitStack()
        self.client = OpenAI()
        self.session: Optional[ClientSession] = None
        self.model = os.environ['MODEL']

    async def connect_to_server(self, server_script_path: str, *args):
        """Connect to the MCP server and list the tools available"""

        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("Server must be .py or .js")

        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path, *args],
            env=None
        )

        # Start MCP server 
        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(
            ClientSession(self.stdio, self.write)
        )
        await self.session.initialize()

        # List the tools available
        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnect to the Server, tools available:", [tool.name for tool in tools])

    async def process_query(self, query: str) -> str:
        """
        LLM to process query and use the tools
        """
        messages = [{"role": "user", "content": query}]
        
    
        response = await self.session.list_tools()
        available_tools = [{
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            }
        } for tool in response.tools]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=available_tools
        )


        content = response.choices[0]

        # Using tools
        if content.finish_reason == "tool_calls":
            tool_call = content.message.tool_calls[0]
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            if hasattr(response.choices[0].message, 'reasoning_content'):
                print(f"[🤖Thinking of tools:]\n {response.choices[0].message.reasoning_content}")

            # Execute tools
            result = await self.session.call_tool(tool_name, tool_args)
            print(f"\n\n[Calling tool {tool_name} with args {tool_args}]\n\n")
        
            # store the history
            messages.append(content.message.model_dump())
            messages.append({
                "role": "tool",
                "content": result.content[0].text,
                "tool_call_id": tool_call.id,
            })

            # send the executing results to the llm and get the final response
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
            )
            return response.choices[0].message.content

        return content.message.content

    async def chat_loop(self):
        """Running the chat looping"""
        print("\n🤖 MCP Client Started!")
        print("Type your queries or 'quit' to exit.")
        while True:
            try:
                query = input("\nYou: ").strip()
                if query.lower() == 'quit':
                    break
                response = await self.process_query(query) 
                print(f"\n[🤖 Response]: {response}")
            except Exception as e:
                print(f"\n[⚠️ Error]: {str(e)}")

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()


async def main():

    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script> <args>")
        sys.exit(1)

    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1], *sys.argv[2:])
        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

