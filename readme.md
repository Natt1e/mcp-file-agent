# MCP-filesystem-python
This is the MCP filesystem server implemented in Python, which is implemented in typescript by modelcontextprotool.(https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem)


## Environment
It is easy to prepare the env.
```
pip install "mcp[cli]" httpx
pip install mcp anthropic python-dotenv
pip install openai
```

## Running
Before running, we should configure our environment varibles, which include:
* OPENAI_API_KEY  : the api_key for calling the llm 
* OPENAI_BASE_URL : the base_url for calling the llm
* MODEL           : the llm name to be used
All we need to do is :
1. create a .env file
2. Write three lines into it , like :
```
OPENAI_API_KEY=sk-xx
OPENAI_BASE_URL=https://api.xxx/v1
MODEL=gpt-4o-mini
```
Then we can run it :
```
python mcpOpenaiClientClient.py filesystemServer.py <target_dir>
```
## Example
```
    -examples
        -little_red.txt 
            This txt describes the story of Little Riding Hood
```
We can try like this :
```
python openai_client.py filesystem ./examples
```